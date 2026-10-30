#!/bin/sh

# PROVIDE: i350_thermal
# REQUIRE: NETWORKING
# KEYWORD: shutdown

. /etc/rc.subr

name="i350_thermal"
rcvar="i350_thermal_enable"

pidfile="/var/run/${name}.pid"
command="/usr/sbin/daemon"

: ${i350_thermal_enable:=NO}

start_cmd="${name}_start"
stop_cmd="${name}_stop"
status_cmd="${name}_status"

i350_thermal_start()
{
    if [ -f "${pidfile}" ]; then
        pid="$(cat "${pidfile}" 2>/dev/null)"

        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            echo "${name} is already running (pid ${pid})"
            return 0
        fi

        rm -f "${pidfile}"
    fi

    echo "Starting ${name}."

    "${command}" \
        -p "${pidfile}" \
        -t "${name}" \
        /usr/local/sbin/i350_thermal_worker

    sleep 1

    if [ -f "${pidfile}" ]; then
        pid="$(cat "${pidfile}")"
        echo "${name} started (pid ${pid})"
        return 0
    fi

    echo "Failed to start ${name}."
    return 1
}

i350_thermal_stop()
{
    if [ ! -f "${pidfile}" ]; then
        echo "${name} is not running."
        return 0
    fi

    pid="$(cat "${pidfile}" 2>/dev/null)"

    if [ -n "${pid}" ]; then
        kill "${pid}" 2>/dev/null
    fi

    sleep 1

    rm -f "${pidfile}"

    echo "${name} stopped."
}

i350_thermal_status()
{
    if [ -f "${pidfile}" ]; then
        pid="$(cat "${pidfile}" 2>/dev/null)"

        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then

            interval=$(
                /usr/local/bin/php -r '
                    require_once("/etc/inc/config.inc");
                    echo config_get_path(
                        "installedpackages/i350thermal/config/0/poll_interval",
                        "5"
                    );
                ' 2>/dev/null
            )

            echo "${name} is running (pid ${pid})"
            echo "Polling interval: ${interval} seconds"
            echo "Cache: /var/run/i350-thermal.json"

            if [ -f /var/run/i350-thermal.json ]; then
                now="$(date +%s)"
                mtime="$(stat -f %m /var/run/i350-thermal.json)"
                echo "Cache age: $((now - mtime)) seconds"
            else
                echo "Cache: not available"
            fi

            return 0
        fi
    fi

    echo "${name} is not running."
    return 1
}

load_rc_config "$name"

run_rc_command "$1"
