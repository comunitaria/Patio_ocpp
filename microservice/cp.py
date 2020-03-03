import asyncio
import websockets
import datetime

from ocpp.v16 import call, ChargePoint as cp
from ocpp.v16.enums import RegistrationStatus, AuthorizationStatus
from ocpp.routing import on
from ocpp.v16.enums import Action
from ocpp.v16 import call, call_result

from . import config

class ChargePoint(cp):
    async def start(self):
        while True:
            message_from_cs = await self._connection.recv()
            print('Id, Msg', self.id, message_from_cs)

            if message_from_cs[0] == 2:
                action = message_from_cs[2]
                data = json.loads(message_from_cs[3])
                print(action)
                if action == Action.RemoteStartTransaction:
                    print("action received")
                    id_tag = data['id_tag']
                    self.on_remote_start_transaction(id_tag)
            else:
                await self.route_message(message_from_cs)


    async def send_boot_notification(self):
        request = call.BootNotificationPayload(
            charge_point_model="Brand",
            charge_point_vendor="The Mobility House",
            charge_point_serial_number="serial123"
        )

        response = await self.call(request)

        if response.status ==  RegistrationStatus.accepted:
            print("Connected to central system.")

    async def send_heartbeat(self):
        request = call.HeartbeatPayload()
        response = await self.call(request)
        print("Heartbeat sent")

    async def send_start_transaction(self):
        # {"connectorId": 0, "idTag": "ABC123", "meterStart": 10, "timestamp":"2019-12-20T00:00:00+00.00"}
        await asyncio.sleep(20)

        request = call.AuthorizePayload(
            id_tag="21",
        )
        response = await self.call(request)

        if response.id_tag_info["status"] ==  AuthorizationStatus.accepted:
            print("User authorized.")

        request = call.StartTransactionPayload(
            connector_id=0,
            id_tag="21",
            meter_start=0,
            timestamp=datetime.datetime.now().isoformat()  #"2019-12-20T00:00:00+00:00"
        )

        response = await self.call(request)

        if response.id_tag_info["status"] ==  AuthorizationStatus.accepted:
            print("Transaction started.")
            self.last_transaction_id = response.transaction_id


    async def send_stop_transaction(self):
        # {"connectorId": 0, "idTag": "ABC123", "meterStart": 10, "timestamp":"2019-12-20T00:00:00+00.00"}
        await asyncio.sleep(50)        
        request = call.StopTransactionPayload(
            transaction_id=self.last_transaction_id,
            meter_stop=20,
            timestamp=datetime.datetime.now().isoformat()  #"2019-12-20T00:30:00+00:00"
        )

        response = await self.call(request)

        if response.id_tag_info["status"] ==  AuthorizationStatus.accepted:
            print("Transaction stopped.")

    @on(Action.RemoteStartTransaction)
    async def on_remote_start_transaction(self, id_tag, **kwargs):
        print("Remote start transaction")
        request = call_result.RemoteStartTransactionPayload(
            status=AuthorizationStatus.accepted,
        )
        return request


async def main():
    async with websockets.connect(
        '%s/serial123' % config.CS_URL,
         subprotocols=['ocpp1.6']
    ) as ws:

        cp = ChargePoint('serial123', ws)

        await asyncio.gather(cp.start(), cp.send_boot_notification(),
                             cp.send_heartbeat(), cp.send_start_transaction(),
                             cp.send_stop_transaction())


if __name__ == '__main__':
    asyncio.run(main())
