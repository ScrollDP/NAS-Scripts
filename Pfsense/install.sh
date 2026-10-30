#!/bin/sh

set -u

NAME="Intel I350 Thermal Monitor"
VERSION="0.1.0"

BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FILES_DIR="${BASE_DIR}/files"

PHP="/usr/local/bin/php"
INSTALL="/usr/bin/install"

READER="/usr/local/bin/i350-thermal"
WORKER="/usr/local/sbin/i350_thermal_worker"
RC_SCRIPT="/usr/local/etc/rc.d/i350_thermal.sh"

WIDGET_INC="/usr/local/www/widgets/include/i350_thermal.inc"
WIDGET_JS="/usr/local/www/widgets/javascript/i350_thermal.js"
WIDGET_PHP="/usr/local/www/widgets/widgets/i350_thermal.widget.php"

CACHE="/var/run/i350-thermal.json"
PIDFILE="/var/run/i350_thermal.pid"

LOG_FILE="/var/log/i350-thermal-install.log"

CONFIG_PATH="installedpackages/i350thermal/config/0"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log()
{
    message="$*"

    printf '%s %s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "${message}" | tee -a "${LOG_FILE}"
}

log_section()
{
    log ""
    log "========================================"
    log "$*"
    log "========================================"
}


die()
{
    log "ERROR: $*"
    exit 1
}


# ---------------------------------------------------------------------------
# Basic checks
# ---------------------------------------------------------------------------

require_root()
{
    if [ "$(id -u)" != "0" ]; then
        die "This script must be run as root."
    fi
}


check_pfsense()
{
    if [ ! -f "/etc/platform" ]; then
        die "This does not appear to be a pfSense system."
    fi

    if ! grep -qi "pfSense" /etc/platform 2>/dev/null; then
        die "This does not appear to be a pfSense system."
    fi

    log "pfSense platform detected."
}


check_commands()
{
    if [ ! -x "${PHP}" ]; then
        die "PHP not found: ${PHP}"
    fi

    if [ ! -x "${INSTALL}" ]; then
        die "install command not found: ${INSTALL}"
    fi
}


# ---------------------------------------------------------------------------
# Package files
# ---------------------------------------------------------------------------

check_files()
{
    log_section "Checking installer files"

    if [ ! -d "${FILES_DIR}" ]; then
        die "Missing files directory: ${FILES_DIR}"
    fi

    for file in \
        i350-thermal \
        i350_thermal_worker \
        i350_thermal.sh \
        i350_thermal.inc \
        i350_thermal.js \
        i350_thermal.widget.php
    do
        if [ ! -f "${FILES_DIR}/${file}" ]; then
            die "Missing package file: ${FILES_DIR}/${file}"
        fi

        log "Found: ${FILES_DIR}/${file}"
    done
}


# ---------------------------------------------------------------------------
# PHP validation
# ---------------------------------------------------------------------------

validate_php_file()
{
    file="$1"

    log "Validating PHP: ${file}"

    output="$("${PHP}" -l "${file}" 2>&1)"
    result=$?

    if [ -n "${output}" ]; then
        printf '%s\n' "${output}" >> "${LOG_FILE}"
    fi

    if [ "${result}" -ne 0 ]; then
        log "PHP syntax error:"
        printf '%s\n' "${output}"
        die "PHP validation failed: ${file}"
    fi

    log "  [OK] ${file}"
}


validate_php()
{
    log_section "Validating PHP"

    log "PHP version:"
    "${PHP}" -v >> "${LOG_FILE}" 2>&1

    "${PHP}" -v

    validate_php_file \
        "${FILES_DIR}/i350_thermal.inc"

    validate_php_file \
        "${FILES_DIR}/i350_thermal.widget.php"

    log "PHP validation completed successfully."
}


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

create_directories()
{
    log_section "Creating directories"

    mkdir -p \
        /usr/local/bin \
        /usr/local/sbin \
        /usr/local/etc/rc.d \
        /usr/local/www/widgets/include \
        /usr/local/www/widgets/javascript \
        /usr/local/www/widgets/widgets \
        || die "Failed to create required directories."

    log "Directories created."
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

stop_service()
{
    log "Checking existing service."

    if [ -x "${RC_SCRIPT}" ]; then
        log "Existing rc.d script found."

        service i350_thermal stop >> "${LOG_FILE}" 2>&1 || true

        sleep 1
    else
        log "No existing rc.d script found."
    fi

    if [ -f "${PIDFILE}" ]; then
        pid="$(cat "${PIDFILE}" 2>/dev/null || true)"

        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            log "Stopping worker PID ${pid}."

            kill "${pid}" 2>/dev/null || true

            i=0

            while kill -0 "${pid}" 2>/dev/null; do
                i=$((i + 1))

                if [ "${i}" -ge 10 ]; then
                    log "Worker did not stop; sending SIGKILL."
                    kill -9 "${pid}" 2>/dev/null || true
                    break
                fi

                sleep 1
            done
        fi

        rm -f "${PIDFILE}"
    fi

    log "Service stopped."
}


start_service()
{
    log_section "Starting service"

    if [ ! -x "${RC_SCRIPT}" ]; then
        log "ERROR: rc.d script is not executable."
        return 1
    fi

    service i350_thermal start >> "${LOG_FILE}" 2>&1

    sleep 1

    if service i350_thermal status >> "${LOG_FILE}" 2>&1; then
        log "  [OK] i350_thermal started."
        return 0
    fi

    log "  [FAIL] i350_thermal did not start."

    return 1
}


# ---------------------------------------------------------------------------
# File installation
# ---------------------------------------------------------------------------

install_file()
{
    source="$1"
    destination="$2"
    mode="$3"

    source_path="${FILES_DIR}/${source}"

    log "Installing:"
    log "  Source: ${source_path}"
    log "  Destination: ${destination}"
    log "  Mode: ${mode}"

    if [ ! -f "${source_path}" ]; then
        die "Source file does not exist: ${source_path}"
    fi

    if ! "${INSTALL}" -m "${mode}" \
        "${source_path}" \
        "${destination}"
    then
        die "Failed to install ${destination}"
    fi

    if [ ! -f "${destination}" ]; then
        die "Installation verification failed: ${destination}"
    fi

    log "  [OK] ${destination}"
}


install_files()
{
    log_section "Installing files"

    install_file \
        "i350-thermal" \
        "${READER}" \
        755

    install_file \
        "i350_thermal_worker" \
        "${WORKER}" \
        755

    install_file \
        "i350_thermal.sh" \
        "${RC_SCRIPT}" \
        755

    install_file \
        "i350_thermal.inc" \
        "${WIDGET_INC}" \
        644

    install_file \
        "i350_thermal.js" \
        "${WIDGET_JS}" \
        644

    install_file \
        "i350_thermal.widget.php" \
        "${WIDGET_PHP}" \
        644

    log "All files installed successfully."
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

set_config_defaults()
{
    log_section "Configuring pfSense"

    "${PHP}" <<'PHP'
<?php

require_once("/etc/inc/config.inc");

if (!isset($config['installedpackages']['i350thermal'])) {
    $config['installedpackages']['i350thermal'] = array();
}

if (!isset($config['installedpackages']['i350thermal']['config'])) {
    $config['installedpackages']['i350thermal']['config'] = array();
}

if (!isset($config['installedpackages']['i350thermal']['config'][0])) {
    $config['installedpackages']['i350thermal']['config'][0] = array();
}

if (!isset($config['installedpackages']['i350thermal']['config'][0]['enable'])) {
    $config['installedpackages']['i350thermal']['config'][0]['enable'] = '1';
}

if (!isset($config['installedpackages']['i350thermal']['config'][0]['poll_interval'])) {
    $config['installedpackages']['i350thermal']['config'][0]['poll_interval'] = '5';
}

write_config("Installed Intel I350 Thermal Monitor.");

PHP

    if [ "$?" -ne 0 ]; then
        die "Failed to configure pfSense."
    fi

    log "  [OK] Configuration"
}


remove_config()
{
    log_section "Removing configuration"

    "${PHP}" <<'PHP'
<?php

require_once("/etc/inc/config.inc");

if (isset($config['installedpackages']['i350thermal'])) {
    unset($config['installedpackages']['i350thermal']);

    write_config("Removed Intel I350 Thermal Monitor configuration.");
}

PHP

    if [ "$?" -ne 0 ]; then
        die "Failed to remove pfSense configuration."
    fi

    log "  [OK] Configuration removed."
}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

remove_cache()
{
    if [ -f "${CACHE}" ]; then
        rm -f "${CACHE}"
        log "Removed cache: ${CACHE}"
    fi
}

# ---------------------------------------------------------------------------
# enable service
# ---------------------------------------------------------------------------

configure_service()
{
    log_section "Configuring service"

    if ! /usr/sbin/sysrc i350_thermal_enable="YES" >> "${LOG_FILE}" 2>&1; then
        die "Failed to enable i350_thermal auto-start."
    fi

    log "  [OK] i350_thermal enabled for automatic startup."
}

disable_service()
{
    log_section "Disabling service"

    /usr/sbin/sysrc -x i350_thermal_enable >> "${LOG_FILE}" 2>&1 || true

    log "  [OK] i350_thermal auto-start disabled."
}

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

install()
{
    require_root
    check_pfsense
    check_commands

    log_section "${NAME}"
    log "Version: ${VERSION}"
    log "Action: install"
    log "Installer directory: ${BASE_DIR}"
    log "Files directory: ${FILES_DIR}"
    log "Log file: ${LOG_FILE}"

    check_files
    validate_php

    create_directories

    log_section "Stopping existing service"

    stop_service

    install_files

    set_config_defaults

    configure_service

    remove_cache

    if ! start_service; then
        die "Installation completed, but the service failed to start."
    fi

    log_section "Installation complete"

    log "Intel I350 Thermal Monitor ${VERSION} installed successfully."
    log "Dashboard widget: Intel I350 Thermal"
    log "Service: i350_thermal"
}


# ---------------------------------------------------------------------------
# Uninstallation
# ---------------------------------------------------------------------------

uninstall()
{
    require_root
    check_pfsense

    log_section "${NAME}"
    log "Version: ${VERSION}"
    log "Action: uninstall"
    log "Installer directory: ${BASE_DIR}"
    log "Log file: ${LOG_FILE}"

    log_section "Stopping existing service"

    stop_service

    if /usr/sbin/sysrc -x i350_thermal_enable >> "${LOG_FILE}" 2>&1; then
        log "Removed i350_thermal.sh auto-start configuration."
    else
        log "Warning: failed to remove i350_thermal.sh auto-start configuration."
    fi

    log_section "Removing files"

    rm -f "${READER}"
    log "Removed: ${READER}"

    rm -f "${WORKER}"
    log "Removed: ${WORKER}"

    rm -f "${RC_SCRIPT}"
    log "Removed: ${RC_SCRIPT}"

    rm -f "${WIDGET_INC}"
    log "Removed: ${WIDGET_INC}"

    rm -f "${WIDGET_JS}"
    log "Removed: ${WIDGET_JS}"

    rm -f "${WIDGET_PHP}"
    log "Removed: ${WIDGET_PHP}"

    remove_cache

    remove_config

    log_section "Uninstallation complete"

    log "Intel I350 Thermal Monitor removed successfully."
}


# ---------------------------------------------------------------------------
# Reinstallation
# ---------------------------------------------------------------------------

reinstall()
{
    require_root
    check_pfsense

    log_section "Reinstalling ${NAME}"

    log "Stopping current installation."

    stop_service

    log "Installing new files."

    install

    log "Reinstallation complete."
}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

status()
{
    check_pfsense

    if [ ! -x "${RC_SCRIPT}" ]; then
        echo "i350_thermal.sh is not installed."
        return 1
    fi

    "${RC_SCRIPT}" status
}


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

usage()
{
    echo
    echo "${NAME} ${VERSION}"
    echo
    echo "Usage:"
    echo
    echo "  $0 install"
    echo "  $0 uninstall"
    echo "  $0 reinstall"
    echo "  $0 status"
    echo
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in

    install)
        install
        ;;

    uninstall)
        uninstall
        ;;

    reinstall)
        reinstall
        ;;

    status)
        status
        ;;

    *)
        usage
        exit 1
        ;;

esac
