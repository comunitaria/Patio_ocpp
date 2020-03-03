# Comunitaria Microservice for compliance with OCPP protocol
- This repository contains the Central System required for communication with Charger Points in the OCPP flow.
-  CP contains a mock charger point with some of Core functions calls for testing purposes against the Central System.
-  Backend operations for users and CP authorization, saving transactions data, requesting of remote transactions by users, ... are managed through the [Smart Community Django app](https://github.com/comunitaria/smartcommunity) from Supervecina.
- config.py file must be created and configured properly, config.py.example can be used as baseline
