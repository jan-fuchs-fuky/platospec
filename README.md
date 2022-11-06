# platospec
Ground-based support for exoplanetary space missions.

## Pucheros Autoguider

![Pucheros Autoguider GUI](doc/screenshot/pucheros_autoguider_gui.png)

## Pucheros Expose

![Pucheros Expose GUI](doc/screenshot/pucheros_expose_gui.png)

## Telescope Control GUI

![Telescope Control GUI](doc/screenshot/telescope_control_gui.png)

## Usage

Set paths **IceSSL.CAs** and **IceSSL.CertFile** in **etc/ice\_client.cfg** and **etc/ice\_server.cfg**.
Certificates and keys for testing purpose are in directory **ssl**.

```
$ cd platospec/telescope/
$ ./test/ascol_simulator.py
$ ICE_CONFIG=/home/user/git/platospec/telescope/etc/ice_server.cfg ./bin/ascol_server.py
$ ICE_CONFIG=/home/user/git/platospec/telescope/etc/ice_client.cfg ./bin/ascol_client_cli.py
```
