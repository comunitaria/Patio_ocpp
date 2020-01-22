import asyncio
import json
import time
import requests
import select
import websockets
import logging

from datetime import datetime
from ocpp.routing import on
from ocpp.messages import Call
from ocpp.v16 import ChargePoint as cp, call, call_result
from ocpp.v16.enums import (Action, RegistrationStatus, RemoteStartStopStatus,
                            AuthorizationStatus, ChargePointStatus)
from dataclasses import asdict
from config import *


def unique_id(): 
    return int(str(time.time()).split('.')[0])


class ChargePointManager(cp):
    authorized = False

    async def start(self):
        logging.basicConfig(filename='cp_%s.log' % self.id, filemode='w',
                            level=logging.INFO)
        self.logger = logging.getLogger("cp_%s" % self.id)

        while True:
            messages = requests.get("%s/%s?token=%s&cp_id=%s" % (BACKEND_URL,
                                                                 "messages",
                                                                 TOKEN, self.id))
            messages = messages.json()['messages']
            for message in messages:
                if message['message'].startswith('remote_start'):
                    order, id_tag = message['message'].split(',')
                    msg = self.remote_start(id_tag)
                    response = msg.to_json()
                    await self._send(response)

            try:
                message_from_cp = await asyncio.wait_for(self._connection.recv(),
                                                         timeout=4)
            except asyncio.TimeoutError:
                continue

            self.logger.info('Msg: %s', message_from_cp)

            if message_from_cp[0] == 3:  # CALLRESULT message type
                # TODO: Check for responses to requests sent by Central System: UnlockConnector, ChangeAvailability, ChangeConfiguration, ClearCache, GetConfiguration, Reset, RemoteStartTransaction
                # (currently not being used)
                action = message_from_cp[2]
                data = json.loads(message_from_cp[3])

                if action == Action.UnlockConnector:
                    pass
                elif action == Action.ChangeAvailability:
                    pass
                elif action == Action.ChangeConfiguration:
                    pass
                elif action == Action.ClearCache:
                    pass
                elif action == Action.GetConfiguration:
                    pass
                elif action == Action.Reset:
                    pass
                elif action == Action.RemoteStartTransaction:
                    status = data['status']
                    if status == RemoteStartStopStatus.rejected:
                        logger.info("Remote start rejected")
                        # TODO: user should be notified to retry

            else:  # CALL message type
                await self.route_message(message_from_cp)

    @on(Action.BootNotification)
    def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        """
            Message example:
            [2, "12345", "BootNotification", {"chargePointVendor": "The Mobility House", "chargePointModel": "Optimus", "chargePointSerialNumber": "ABC123"}]
        """
        status = RegistrationStatus.rejected
        serial_id = kwargs.get('charge_point_serial_number',
                               'No serial number')

        # Accept or reject request based on CP serial number
        # TODO: Accept or reject based on IP or MAC of CP
        response = requests.post("%s/%s" % (BACKEND_URL, "authorize_cp"),
                                 json={'token': TOKEN,
                                       'cp_id': serial_id})
        if response.ok and response.json()['status'] == 'ok':
            status = RegistrationStatus.accepted
            self.authorized = True

        return call_result.BootNotificationPayload(
            current_time=datetime.utcnow().isoformat(),
            interval=10,
            status=status
        )

    def remote_start(self, id_tag, **kwargs):
        """
            Send remote start transaction to CP
        """
        msg = Call(str(self._unique_id_generator()), "RemoteStartTransaction", {"idTag":id_tag}) # id tag 20 chars len max
        return msg

    @on(Action.StartTransaction)
    def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
        """
            Message example:
            [2, "12345", "StartTransaction", {"connectorId": 0, "idTag": "ABC123", "meterStart": 10, "timestamp":"2019-12-20T00:00:00+00.00"}]
        """

        # Query to Supervecina to get a new transaction id for the user
        response = requests.post("%s/%s" % (BACKEND_URL, "new_transaction"),
                                 json={'token': TOKEN,
                                       'user_id': id_tag})

        response_json = response.json()

        status = AuthorizationStatus.invalid
        if response.ok and response_json['status'] == 'ok' and self.authorized:
            # If user is authorized, check if CP was previously authorized
            status = AuthorizationStatus.accepted

        return call_result.StartTransactionPayload(
            id_tag_info={"status": status},
            transaction_id=response.json().get('transaction_id', 0)
        )

    @on(Action.StopTransaction)
    def on_stop_transaction(self, meter_stop, timestamp, transaction_id, **kwargs):
        """
            Message example:
            [2, "12345", "StopTransaction", {"transaction_id": "123", "meterStop": 10, "timestamp":"2019-12-20T00:00:00+00.00"}]
        """

        data = {"amount": meter_stop,  # integer in Wh
                "datetime": timestamp,
                "transaction_id": transaction_id,
                "cp_id": self.id
                }

        # Publish to IOTA
        response = requests.get(IOTA_PUBLISHER_URL,
                                params={"message": json.dumps(data)})
        response = response.json()
        mam_address = response['root']

        # Save energy consumption information
        response = requests.post("%s/%s" % (BACKEND_URL, "save_cp_energy"),
                                 json={'token': TOKEN,
                                       'datetime': timestamp,
                                       'amount': meter_stop,
                                       'cp_id': self.id,
                                       'mam_address': mam_address,
                                       'transaction_id': transaction_id})
        status = AuthorizationStatus.accepted

        return call_result.StopTransactionPayload(
            id_tag_info={"status": status},
        )


    @on(Action.MeterValues)
    def on_metervalues(self, connector_id, meter_value, **kwargs):
        return call_result.MeterValuesPayload()


    @on(Action.Heartbeat)
    def on_heartbeat(self):
        return call_result.HeartbeatPayload(
            current_time=datetime.utcnow().isoformat()
        )


    @on(Action.Authorize)
    def on_authorize(self, id_tag):
        # Query to Supervecina to check if id_tag (user id) is authorized
        response = requests.post("%s/%s" % (BACKEND_URL, "authorize_user"),
                                 json={'token': TOKEN,
                                       'user_id': id_tag,
                                       'cp_id': self.id})

        response_json = response.json()

        status = AuthorizationStatus.invalid
        if response.ok and response_json['status'] == 'ok' and self.authorized:
            # If user is authorized, check if CP was previously authorized
            status = AuthorizationStatus.accepted

        return call_result.AuthorizePayload(
            id_tag_info={"status": status}
        )

    @on(Action.StatusNotification)
    def on_status_notification(self, connector_id, error_code, status, **kwargs):
        operative_status = "operative"

        if status in [ChargePointStatus.unavailable, ChargePointStatus.faulted]:
            operative_status = "inoperative"

        # Save CP status and error code
        response = requests.post("%s/%s" % (BACKEND_URL, "cp_status_update"),
                                 json={"token": TOKEN,
                                       "status": operative_status,
                                       "error_code": error_code,
                                       "cp_id": self.id})

        return call_result.StatusNotificationPayload()


async def on_connect(websocket, path):
    """ For every new charge point that connects, create a ChargePointManager
        instance and start listening for messages.
    """
    charge_point_id = path.strip('/')
    cp = ChargePointManager(charge_point_id, websocket)

    await cp.start()


async def main():
   server = await websockets.serve(
      on_connect,
      '0.0.0.0',
      9000,
      subprotocols=['ocpp1.6']
   )

   await server.wait_closed()


if __name__ == '__main__':
   asyncio.run(main())
