# Intel I350 Thermal Monitor for pfSense

A lightweight pfSense dashboard widget and background monitor for Intel
I350-based network adapters.

The monitor reads the Intel I350 thermal registers directly through the
FreeBSD `pciconf` interface and exposes the information through a
pfSense dashboard widget.

This project is intended primarily for Intel I350-T4 adapters.

---

## Features

- Detects Intel I350 devices using PCI vendor/device IDs.
- Does not rely only on the `igb` driver name.
- Groups the four PCI functions of an I350-T4 into one physical adapter.
- Reads the Intel I350 junction temperature register.
- Reports thermal thresholds:
  - Low
  - Mid
  - High
- Reports thermal status:
  - Thermal throttle
  - Power-down event
  - Low temperature event
  - Mid temperature event
  - High temperature event
- Provides a JSON output mode.
- Maintains a small runtime cache in `/var/run`.
- Uses a background polling worker.
- Provides a pfSense dashboard widget.
- Widget updates automatically using pfSense AJAX infrastructure.
- Configurable polling interval.
- Can be installed, uninstalled, reinstalled, or queried using one script.

---

# Requirements

## Operating system

Designed for:

    pfSense CE 2.9.0

It may work on other pfSense versions, but compatibility with versions
other than the development target has not been tested.

## Hardware

The monitor is designed for:

    Intel I350

For an Intel I350-T4, the four ports normally appear as:

    igb0
    igb1
    igb2
    igb3

The physical PCI device may appear as:

    pci0:1:0

with the individual functions:

    pci0:1:0:0
    pci0:1:0:1
    pci0:1:0:2
    pci0:1:0:3

The monitor identifies the hardware using:

    PCI vendor: 0x8086
    PCI device: 0x1521

This is intentional. The program does not assume that every `igb`
interface is an Intel I350.

---

# Installation

Copy the ZIP file to the pfSense firewall.

For example, if the archive is:

    i350-thermal.zip

extract it:

    cd /tmp
    unzip i350-thermal.zip

Enter the directory:

    cd i350-thermal

Make the installer executable:

    chmod +x install.sh

Install:

    ./install.sh install

The installer will:

1. Verify that it is running as root.
2. Verify that the system appears to be pfSense.
3. Check that all required files exist.
4. Validate the PHP files.
5. Create required directories.
6. Stop an existing I350 thermal worker if present.
7. Install the thermal reader.
8. Install the background worker.
9. Install the rc.d service script.
10. Install the pfSense dashboard widget files.
11. Create the initial pfSense configuration.
12. Remove an old runtime cache.
13. Start the monitoring service.

---

# Installed files

The installer places the following files on pfSense.

## Thermal reader

    /usr/local/bin/i350-thermal

This is the low-level reader.

It can be executed manually:

    /usr/local/bin/i350-thermal

JSON output:

    /usr/local/bin/i350-thermal --json

Optional interface argument:

    /usr/local/bin/i350-thermal igb0

The JSON output is intended to be consumed by the background worker and
dashboard widget.

---

## Background worker

    /usr/local/sbin/i350_thermal_worker

The worker periodically executes:

    /usr/local/bin/i350-thermal --json

and stores the result in:

    /var/run/i350-thermal.json

The cache is replaced atomically so that the dashboard never reads a
partially written JSON file.

The worker reads its configuration from the pfSense configuration.

---

## Service script

    /usr/local/etc/rc.d/i350_thermal

The service can be controlled using:

    /usr/local/etc/rc.d/i350_thermal start
    /usr/local/etc/rc.d/i350_thermal stop
    /usr/local/etc/rc.d/i350_thermal restart
    /usr/local/etc/rc.d/i350_thermal status

The service uses:

    /var/run/i350_thermal.pid

for its PID file.

---

# Dashboard widget

The following files implement the pfSense dashboard widget:

    /usr/local/www/widgets/include/i350_thermal.inc
    /usr/local/www/widgets/javascript/i350_thermal.js
    /usr/local/www/widgets/widgets/i350_thermal.widget.php

The widget follows the normal pfSense dashboard widget architecture.

The JavaScript uses the pfSense `register_ajax()` mechanism to periodically
refresh the widget.

The widget instance passes its own pfSense widget key through the HTML:

    data-widget-key="..."

This allows the widget to work correctly with its individual dashboard
instance.

---

# Configuration

The monitor stores its configuration in the pfSense configuration:

    installedpackages/i350thermal/config/0/

The following values are used.

## Enable

    enable

Default:

    1

Possible values:

    1
    0

When disabled, the background worker removes the runtime cache and does
not perform thermal polling.

---

## Polling interval

    poll_interval

Default:

    5

The value is expressed in seconds.

Allowed range:

    1 - 60 seconds

The worker reads this value during operation, so changing the polling
interval does not require restarting the service.

This is intentional.

The dashboard widget also uses the configured interval for its AJAX
refresh frequency.

---

# Runtime cache

The current thermal data is stored in:

    /var/run/i350-thermal.json

This file is runtime state and is not intended to survive a reboot.

Example:

    {
        ...
    }

The exact JSON fields may change as the thermal reader is developed.

The dashboard widget treats the cache as stale when it has not been
updated within the configured stale-data threshold.

---

# Temperature information

The Intel I350 junction temperature register is:

    THMJT
    Offset: 0x8100

The temperature value uses the register's temperature field.

The monitor also reads the Intel I350 thermal threshold registers:

    THLOWTC
    Offset: 0x8104

    THMIDTC
    Offset: 0x8108

    THHIGHTC
    Offset: 0x810C

Thermal status information is read from:

    THSTAT
    Offset: 0x8110

The monitor reports the values but does not modify the thermal
thresholds.

---

# Important safety note

This software is intended to monitor the I350 thermal state.

It does NOT modify:

- thermal thresholds
- EEPROM contents
- adapter configuration
- power-management settings
- NIC registers other than reading the required thermal registers

The monitor is therefore intended to be read-only with respect to the
thermal hardware.

---

# Checking the installation

After installation:

    ./install.sh status

The service should report something similar to:

    i350_thermal is running (pid XXXXX)
    Polling interval: 5 seconds
    Cache: /var/run/i350-thermal.json
    Cache age: 1 seconds

You can also check the service directly:

    /usr/local/etc/rc.d/i350_thermal status

---

# Checking the thermal reader

Run:

    /usr/local/bin/i350-thermal

For machine-readable output:

    /usr/local/bin/i350-thermal --json

The JSON output can be checked with PHP:

    /usr/local/bin/i350-thermal --json | \
        /usr/local/bin/php -r \
        '$j=stream_get_contents(STDIN); \
        json_decode($j,true); \
        echo json_last_error_msg(),PHP_EOL;'

Expected result:

    No error

---

# Checking the runtime cache

Run:

    ls -lh /var/run/i350-thermal.json

Then:

    cat /var/run/i350-thermal.json

The cache should contain the most recent successful reading.

---

# Dashboard installation

After installing the files, open the pfSense dashboard.

Use the dashboard widget management interface to add:

    Intel I350 Thermal

The widget can then be positioned like any other pfSense dashboard
widget.

The widget configuration panel allows:

- enabling/disabling monitoring
- selecting the polling interval

After saving the widget configuration, the background worker reads the
new configuration automatically.

A service restart is not required when changing the polling interval.

---

# Uninstallation

To remove the monitor:

    ./install.sh uninstall

The uninstall procedure:

1. Stops the monitoring worker.
2. Removes the thermal reader.
3. Removes the worker.
4. Removes the rc.d service script.
5. Removes the dashboard widget PHP file.
6. Removes the widget JavaScript.
7. Removes the widget include file.
8. Removes the runtime cache.
9. Removes the I350 Thermal configuration from pfSense.

It does not intentionally remove unrelated pfSense files.

---

# Reinstallation

To completely remove and reinstall:

    ./install.sh reinstall

This performs:

    uninstall
    install

A reinstall is useful while developing or testing new versions.

---

# Service status

The following command can be used at any time:

    ./install.sh status

or:

    /usr/local/etc/rc.d/i350_thermal status

---

# Development workflow

The project is intentionally structured so that the files can be edited
without rebuilding a pfSense package.

Project:

    i350-thermal/
    ├── README.md
    ├── install.sh
    └── files/
        ├── i350-thermal
        ├── i350_thermal_worker
        ├── i350_thermal
        ├── i350_thermal.inc
        ├── i350_thermal.js
        └── i350_thermal.widget.php

After modifying a file, copy the updated project to pfSense and run:

    ./install.sh reinstall

This stops the old service, replaces the files, recreates the
configuration if necessary, and starts the new version.

---

# Troubleshooting

## Worker is not running

Check:

    /usr/local/etc/rc.d/i350_thermal status

Try:

    /usr/local/etc/rc.d/i350_thermal start

Then:

    /usr/local/etc/rc.d/i350_thermal status

---

## No cache file

Check:

    ls -l /var/run/i350-thermal.json

If it does not exist, check whether monitoring is enabled:

    php -r '
    require_once("/etc/inc/config.inc");
    var_dump(config_get_path(
        "installedpackages/i350thermal/config/0/enable",
        "1"
    ));
    '

Then run the reader directly:

    /usr/local/bin/i350-thermal --json

If the reader itself produces no valid output, the problem is with
hardware detection or thermal register access rather than the worker.

---

## Check PCI detection

Run:

    pciconf -l | grep -i 1521

An I350 should contain PCI device ID:

    0x1521

The Intel vendor ID is:

    0x8086

---

## Check interfaces

Run:

    ifconfig -l

An I350-T4 will normally expose four `igb` interfaces, for example:

    igb0 igb1 igb2 igb3

The exact interface numbers can differ depending on the system.

---

## PHP syntax errors

Run:

    php -l /usr/local/www/widgets/widgets/i350_thermal.widget.php

and:

    php -l /usr/local/www/widgets/include/i350_thermal.inc

Both should report:

    No syntax errors detected

---

## Dashboard JavaScript errors

Open the browser developer console.

Check that the widget has:

    data-widget-key="i350_thermal-0"

For example:

    $('.i350-thermal-widget').attr('data-widget-key')

should return something similar to:

    "i350_thermal-0"

The AJAX request should contain:

    ajax=ajax
    widgetkey=i350_thermal-0

---

# Removing old development files

If an older manually installed version exists, use:

    ./install.sh uninstall

before installing the new version.

Do not manually delete individual widget files unless necessary.

---

# Current architecture

The system consists of four main parts:

    Intel I350
        |
        | thermal registers
        v
    /usr/local/bin/i350-thermal
        |
        | JSON
        v
    /var/run/i350-thermal.json
        |
        v
    pfSense dashboard widget


The background worker sits between the reader and dashboard:

    i350-thermal
          |
          v
    i350_thermal_worker
          |
          v
    /var/run/i350-thermal.json
          |
          v
    i350_thermal.widget.php
          |
          v
    i350_thermal.js
          |
          v
    pfSense Dashboard

---

# Why a background worker is used

The dashboard should not directly access the hardware every time it
refreshes.

Instead:

1. The worker polls the hardware.
2. The worker writes the latest valid JSON result.
3. The dashboard reads the cached result.
4. The dashboard refreshes independently using pfSense AJAX.

This keeps hardware access separate from the web interface.

It also prevents repeated hardware access by multiple dashboard
requests.

---

# Files intentionally not included

The project does not modify:

- pfSense base system files
- NIC EEPROM
- thermal threshold registers
- `/etc/rc.conf`
- unrelated dashboard widgets
- unrelated pfSense configuration
- network interface configuration

The only persistent pfSense configuration created by this project is:

    installedpackages/i350thermal/

---

# Version

Current development version:

    0.1.0

This is a development/manual-install version and is not currently a
formal package distributed through the pfSense package repository.

---

# Author

Scroll_DP

email: darwin@ifala.eu
---

# License

BSD2CLAUSE 
