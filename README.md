# platospec
Ground-based support for exoplanetary space missions.

```
workstation$ git clone https://github.com/jan-fuchs-fuky/platospec.git platospec
```

## Pucheros Autoguider GUI

### Run

```
workstation$ ./platospec/indi_autoguider/bin/indi_autoguider.py
```

![Pucheros Autoguider GUI](doc/screenshot/pucheros_autoguider_gui.png)
![Pucheros Autoguider GUI Scan](doc/screenshot/pucheros_autoguider_gui_scan.png)

## Pucheros Expose GUI

### Run

```
workstation$ ./platospec/pucheros_expose_gui/bin/pucheros_expose.py
```

![Pucheros Expose GUI](doc/screenshot/pucheros_expose_gui.png)

## Telescope Control GUI

### Run

Create wrapper **telescope_control_gui**:

```
#!/bin/bash

export ICE_CONFIG=/home/user/platospec/telescope_control_gui/etc/ice_client.cfg

/home/user/platospec/telescope_control_gui/bin/ascol_client.py

```

Add execute permission and run:

```
workstation$ chmod +x telescope_control_gui
workstation$ ./telescope_control_gui
```

![Telescope Control GUI](doc/screenshot/telescope_control_gui.png)

## E152 Watchdog GUI

### Run

```
workstation$ ./platospec/e152_watchdog/bin/e152_watchdog.py
```

![E152 Watchdog GUI](doc/screenshot/e152_watchdog_gui.png)

## Usage

Set paths **IceSSL.CAs** and **IceSSL.CertFile** in **etc/ice\_client.cfg** and **etc/ice\_server.cfg**.
Certificates and keys for testing purpose are in directory **ssl**.

```
$ cd platospec/telescope/
$ ./test/ascol_simulator.py
$ ICE_CONFIG=/home/user/git/platospec/telescope/etc/ice_server.cfg ./bin/ascol_server.py
$ ICE_CONFIG=/home/user/git/platospec/telescope/etc/ice_client.cfg ./bin/ascol_client_cli.py
```
