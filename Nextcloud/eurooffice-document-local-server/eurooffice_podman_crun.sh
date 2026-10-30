#!/bin/bash

# Script used for unprivileged LXC containers.
# Podman + crun, automatic updates, persistent volumes,
# automatic Nextcloud data-directory detection, and install/update/reinstall/uninstall.

true
SCRIPT_NAME="EuroOffice (Podman)"
SCRIPT_EXPLAINER="Install or update EuroOffice Document Server using Podman and crun"

# shellcheck source=lib.sh
source /var/scripts/fetch_lib.sh

DEBUG=0
debug_mode
root_check

# --------------------------------------------------
# Configuration
# --------------------------------------------------

EUROOFFICE_IMAGE="ghcr.io/euro-office/documentserver:latest"
EUROOFFICE_CONTAINER="eurooffice"
EUROOFFICE_RUNTIME="/usr/bin/crun"
EUROOFFICE_JWT_HEADER="AuthorizationJwt"
EUROOFFICE_DEFAULT_PORT=9980

# These are discovered at runtime. No settings file is used.
EUROOFFICE_DATA_DIR=""
EUROOFFICE_BIND_IP=""
EUROOFFICE_PORT="$EUROOFFICE_DEFAULT_PORT"
EUROOFFICE_PUBLIC_URL=""
EUROOFFICE_INTERNAL_URL=""
EUROOFFICE_SECRET=""
NC_URL=""
NC_DATA_DIR=""
NCDOMAIN=""
FORCE_RECREATE=false
ACTION="update"

# --------------------------------------------------
# Podman helpers
# --------------------------------------------------

podman_crun() {
    podman --runtime "$EUROOFFICE_RUNTIME" "$@"
}

podman_image_exists() {
    podman_crun image exists "$1" >/dev/null 2>&1
}

podman_container_exists() {
    podman_crun container exists "$1" >/dev/null 2>&1
}

get_image_id() {
    podman_crun image inspect "$1" --format '{{.Id}}' 2>/dev/null
}

get_container_image_id() {
    podman_crun inspect "$1" --format '{{.Image}}' 2>/dev/null
}

container_running() {
    [ "$(podman_crun inspect "$EUROOFFICE_CONTAINER" \
        --format '{{.State.Running}}' 2>/dev/null)" = "true" ]
}

# --------------------------------------------------
# Uninstall EuroOffice
# --------------------------------------------------

uninstall_eurooffice() {
    if ! yesno_box_yes "Uninstall EuroOffice?

The container, image, and Nextcloud connector will be removed.

Persistent data and configuration under:
${EUROOFFICE_DATA_DIR:-the detected Nextcloud data directory}/eurooffice

will be preserved."; then
        return 1
    fi

    print_text_in_color "$ICyan" "Removing EuroOffice..."

    if podman_container_exists "$EUROOFFICE_CONTAINER"; then
        podman_crun rm -f "$EUROOFFICE_CONTAINER" || true
    fi

    # Remove a legacy Docker container if present.
    if command -v docker >/dev/null 2>&1; then
        docker rm -f "$EUROOFFICE_CONTAINER" >/dev/null 2>&1 || true
    fi

    if nextcloud_occ app:list --enabled 2>/dev/null | grep -q 'eurooffice'; then
        nextcloud_occ app:disable eurooffice || true
    fi

    if [ -d "/var/www/nextcloud/apps/eurooffice" ]; then
        nextcloud_occ app:remove eurooffice || true
    fi

    nextcloud_occ config:app:delete eurooffice jwt_secret 2>/dev/null || true
    nextcloud_occ config:app:delete eurooffice jwt_header 2>/dev/null || true

    if podman_image_exists "$EUROOFFICE_IMAGE"; then
        podman_crun rmi "$EUROOFFICE_IMAGE" || true
    fi

    msg_box "EuroOffice has been uninstalled.

Persistent data and configuration have been preserved."
    exit 0
}

# --------------------------------------------------
# Detect Nextcloud URLs and data directory
# --------------------------------------------------

detect_nextcloud_settings() {
    NC_URL="$(nextcloud_occ_no_check config:system:get overwrite.cli.url 2>/dev/null)"
    NC_URL="${NC_URL%/}"

    if [ -z "$NC_URL" ]; then
        msg_box "Unable to determine Nextcloud's overwrite.cli.url."
        return 1
    fi

    NCDOMAIN="$(printf '%s' "$NC_URL" | sed -E 's|^https?://||; s|/.*$||')"

    NC_DATA_DIR="$(nextcloud_occ_no_check config:system:get datadirectory 2>/dev/null)"
    NC_DATA_DIR="${NC_DATA_DIR%/}"

    # If OCC cannot determine the data directory, ask the administrator.
    if [ -z "$NC_DATA_DIR" ] || [ ! -d "$NC_DATA_DIR" ]; then
        msg_box "The Nextcloud data directory could not be detected automatically.

Please enter its absolute path in the next dialog."
        NC_DATA_DIR="$(input_box_flow \
            "Nextcloud data directory.

Enter the absolute path to the existing Nextcloud data directory." \
            "/mnt/ncdata")"
        NC_DATA_DIR="${NC_DATA_DIR%/}"
    fi

    if [ -z "$NC_DATA_DIR" ] || [ ! -d "$NC_DATA_DIR" ]; then
        msg_box "Invalid Nextcloud data directory:
${NC_DATA_DIR:-<empty>}

No changes have been made."
        return 1
    fi

    EUROOFFICE_DATA_DIR="${NC_DATA_DIR}/eurooffice"
    EUROOFFICE_PUBLIC_URL="$(nextcloud_occ_no_check config:app:get eurooffice DocumentServerUrl 2>/dev/null)"
    EUROOFFICE_PUBLIC_URL="${EUROOFFICE_PUBLIC_URL%/}"

    # Prefer the existing container's published port mapping for defaults.
    if podman_container_exists "$EUROOFFICE_CONTAINER"; then
        local published
        published="$(podman_crun port "$EUROOFFICE_CONTAINER" 80/tcp 2>/dev/null | head -n1)"
        if [[ "$published" =~ ^([^:]+):([0-9]+)$ ]]; then
            EUROOFFICE_BIND_IP="${BASH_REMATCH[1]}"
            EUROOFFICE_PORT="${BASH_REMATCH[2]}"
        fi
    fi

    # Existing Nextcloud configuration is the best source for the public URL.
    if [ -n "$EUROOFFICE_PUBLIC_URL" ] && [[ "$EUROOFFICE_PUBLIC_URL" != https://* ]]; then
        EUROOFFICE_PUBLIC_URL="https://${EUROOFFICE_PUBLIC_URL#http://}"
    fi

    return 0
}

# --------------------------------------------------
# Installation action menu
# --------------------------------------------------

choose_action() {
    local answer

    if ! podman_container_exists "$EUROOFFICE_CONTAINER" &&
       ! podman_image_exists "$EUROOFFICE_IMAGE"; then
        if command -v whiptail >/dev/null 2>&1; then
            answer="$(whiptail --title "EuroOffice" \
                --menu "EuroOffice is not installed. Choose an action:" \
                15 72 2 \
                install "Install EuroOffice Document Server" \
                cancel "Cancel and exit" 3>&1 1>&2 2>&3)" || exit 0
        elif command -v dialog >/dev/null 2>&1; then
            answer="$(dialog --title "EuroOffice" \
                --menu "EuroOffice is not installed. Choose an action:" \
                15 72 2 \
                install "Install EuroOffice Document Server" \
                cancel "Cancel and exit" 3>&1 1>&2 2>&3)" || exit 0
        else
            msg_box "Neither whiptail nor dialog is installed; cannot show the keyboard menu."
            exit 1
        fi
        [ "$answer" = "install" ] || exit 0
        ACTION="install"
        return 0
    fi

    if command -v whiptail >/dev/null 2>&1; then
        answer="$(whiptail --title "EuroOffice" \
            --menu "EuroOffice installation detected. Use arrow keys and Enter:" \
            18 78 4 \
            update "Update; recreate only if needed" \
            reinstall "Reinstall; force container recreation" \
            uninstall "Uninstall; preserve persistent data" \
            cancel "Cancel and exit without changes" 3>&1 1>&2 2>&3)" || exit 0
    elif command -v dialog >/dev/null 2>&1; then
        answer="$(dialog --title "EuroOffice" \
            --menu "EuroOffice installation detected. Use arrow keys and Enter:" \
            18 78 4 \
            update "Update; recreate only if needed" \
            reinstall "Reinstall; force container recreation" \
            uninstall "Uninstall; preserve persistent data" \
            cancel "Cancel and exit without changes" 3>&1 1>&2 2>&3)" || exit 0
    else
        msg_box "Neither whiptail nor dialog is installed; cannot show the keyboard menu."
        exit 1
    fi

    case "$answer" in
        update) ACTION="update" ;;
        reinstall) ACTION="reinstall"; FORCE_RECREATE=true ;;
        uninstall) ACTION="uninstall" ;;
        cancel|"") exit 0 ;;
        *) msg_box "Unknown menu selection: $answer"; exit 1 ;;
    esac
}

# --------------------------------------------------
# Network detection
# --------------------------------------------------

detect_local_ip() {
    local ip
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null |
        awk '{
            for (i = 1; i <= NF; i++) {
                if ($i == "src") {
                    print $(i + 1)
                    exit
                }
            }
        }')"

    if [ -z "$ip" ]; then
        ip="$(ip -o -4 addr show scope global |
            awk 'NR == 1 { split($4, a, "/"); print a[1] }')"
    fi

    printf '%s\n' "$ip"
}

configure_network() {
    local detected_ip="$1"
    local ip_default="${EUROOFFICE_BIND_IP:-$detected_ip}"
    local port_default="${EUROOFFICE_PORT:-$EUROOFFICE_DEFAULT_PORT}"
    local input_value
    local default_domain
    local office_host

    [ -n "$ip_default" ] || ip_default="$detected_ip"
    [ -n "$port_default" ] || port_default="$EUROOFFICE_DEFAULT_PORT"

    if [ -n "$EUROOFFICE_PUBLIC_URL" ]; then
        default_domain="$(printf '%s' "$EUROOFFICE_PUBLIC_URL" | sed -E 's|^https?://||; s|/.*$||')"
    else
        default_domain="office.${NCDOMAIN}"
    fi

    # Confirm detected/current values first. This avoids depending on whether
    # input_box_flow correctly pre-populates its input field.
    # Confirm only the bind address and port. The public hostname is always
    # requested separately below.
    if yesno_box_yes "Are these EuroOffice bind settings correct?

Bind IPv4: ${ip_default:-<not detected>}
Host port: ${port_default}

Choose Yes to accept these two values. Choose No to edit them.

The public hostname will be requested separately."; then
        EUROOFFICE_BIND_IP="$ip_default"
        EUROOFFICE_PORT="$port_default"
    else
        while true; do
            input_value="$(input_box_flow \
                "EuroOffice bind IPv4 address.

Suggested value: ${ip_default:-<not detected>}
Enter a different IPv4 address, or press Enter to keep the suggested value." \
                "$ip_default")"
            [ -n "$input_value" ] || input_value="$ip_default"
            EUROOFFICE_BIND_IP="$input_value"

            if [ -z "$EUROOFFICE_BIND_IP" ]; then
                msg_box "No IPv4 address was detected. Enter an address manually."
                continue
            fi
            if ! python3 - "$EUROOFFICE_BIND_IP" <<'PYIP'
import ipaddress
import sys
try:
    address = ipaddress.ip_address(sys.argv[1])
    sys.exit(0 if address.version == 4 else 1)
except ValueError:
    sys.exit(1)
PYIP
            then
                msg_box "Invalid IPv4 address: ${EUROOFFICE_BIND_IP}\n\nPlease try again."
                continue
            fi
            if ! ip -o -4 addr show | awk '{split($4,a,"/"); print a[1]}' | grep -Fxq "$EUROOFFICE_BIND_IP"; then
                msg_box "IP address ${EUROOFFICE_BIND_IP} is not assigned to this machine.\n\nPlease try again."
                continue
            fi
            break
        done

        while true; do
            input_value="$(input_box_flow \
                "EuroOffice host port.

Suggested value: ${port_default}
Enter a different port, or press Enter to keep the suggested value." \
                "$port_default")"
            [ -n "$input_value" ] || input_value="$port_default"
            EUROOFFICE_PORT="$input_value"
            if ! [[ "$EUROOFFICE_PORT" =~ ^[0-9]+$ ]] ||
               [ "$EUROOFFICE_PORT" -lt 1 ] || [ "$EUROOFFICE_PORT" -gt 65535 ]; then
                msg_box "Invalid port: ${EUROOFFICE_PORT}\n\nEnter a number from 1 to 65535 and try again."
                continue
            fi
            break
        done

    fi

    # Always ask for the public hostname separately, regardless of whether
    # the bind IPv4 address and port were accepted or edited.
    while true; do
        input_value="$(input_box_flow \
            "EuroOffice public hostname only (no https:// and no trailing slash).

Example: office.example.com

Nextcloud hostname: ${NCDOMAIN}" \
            "$default_domain")"

        if [ -z "$input_value" ]; then
            msg_box "The public hostname cannot be empty. Please try again."
            continue
        fi

        # Tolerate a pasted scheme/trailing slash, then normalize to hostname.
        office_host="$(printf '%s' "$input_value" | sed -E 's|^https?://||; s|/.*$||; s/[[:space:]]//g')"
        if [ -z "$office_host" ]; then
            msg_box "Invalid hostname. Enter a domain such as office.ifala.eu."
            continue
        fi

        if [ "$office_host" = "$NCDOMAIN" ]; then
            msg_box "EuroOffice must use a different hostname from Nextcloud. Please try again."
            continue
        fi

        if ! [[ "$office_host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] ||
           [[ "$office_host" == *..* ]] || [[ "$office_host" == *.-* ]] || [[ "$office_host" == *-. ]]; then
            msg_box "Invalid hostname: ${office_host}\n\nExample: office.ifala.eu"
            continue
        fi
        break
    done

    # Validate the accepted defaults too, in case detection returned stale data.
    if ! python3 - "$EUROOFFICE_BIND_IP" <<'PYIP'
import ipaddress
import sys
try:
    address = ipaddress.ip_address(sys.argv[1])
    sys.exit(0 if address.version == 4 else 1)
except ValueError:
    sys.exit(1)
PYIP
    then
        msg_box "The suggested bind address is missing or invalid: ${EUROOFFICE_BIND_IP:-<empty>}.
Please run the configuration again and choose No to enter it manually."
        return 1
    fi
    if ! ip -o -4 addr show | awk '{split($4,a,"/"); print a[1]}' | grep -Fxq "$EUROOFFICE_BIND_IP"; then
        msg_box "The selected IP address ${EUROOFFICE_BIND_IP} is not assigned to this machine.
Please run the configuration again and choose No to enter it manually."
        return 1
    fi
    if ! [[ "$EUROOFFICE_PORT" =~ ^[0-9]+$ ]] || [ "$EUROOFFICE_PORT" -lt 1 ] || [ "$EUROOFFICE_PORT" -gt 65535 ]; then
        msg_box "The selected port is invalid: ${EUROOFFICE_PORT}"
        return 1
    fi

    EUROOFFICE_INTERNAL_URL="http://${EUROOFFICE_BIND_IP}:${EUROOFFICE_PORT}/"
    EUROOFFICE_PUBLIC_URL="https://${office_host}/"
}

# --------------------------------------------------
# Persistent volume preparation
# --------------------------------------------------

prepare_eurooffice_volumes() {
    local base_dir="$EUROOFFICE_DATA_DIR"

    print_text_in_color "$ICyan" "Preparing EuroOffice persistent volumes..."

    mkdir -p \
        "$base_dir/data" \
        "$base_dir/config" \
        "$base_dir/runtime" || {
            echo "ERROR: Failed to create EuroOffice directories."
            return 1
        }

    chown 105:107 "$base_dir/data" "$base_dir/runtime" || {
        echo "ERROR: Failed to set volume ownership."
        return 1
    }

    chmod 755 "$base_dir/data" || return 1
    chmod 2775 "$base_dir/runtime" || return 1
    chmod 755 "$base_dir/config" || return 1

    # Initialize configuration from the image on a fresh installation.
    # Existing configuration is never overwritten.
    if [ ! -s "$base_dir/config/local.json" ]; then
        print_text_in_color "$ICyan" \
            "Initializing EuroOffice configuration from the image..."

        podman_crun run --rm \
            --entrypoint /bin/sh \
            -v "$base_dir/config:/host-config" \
            "$EUROOFFICE_IMAGE" \
            -c 'cp -an /etc/euro-office/documentserver/. /host-config/' || {
                echo "ERROR: Failed to initialize EuroOffice configuration."
                return 1
            }
    fi

    if [ ! -s "$base_dir/config/local.json" ]; then
        echo "ERROR: local.json is missing or empty."
        return 1
    fi

    print_text_in_color "$IGreen" "Persistent volumes prepared."
}

# --------------------------------------------------
# Begin installation flow
# --------------------------------------------------

# Install/check Podman and crun before using the helpers.
if ! command -v podman >/dev/null 2>&1 ||
   ! command -v crun >/dev/null 2>&1; then
    apt-get update -q4 & spinner_loading
    apt-get install -y podman crun || {
        msg_box "Unable to install Podman and crun."
        exit 1
    }
fi

if [ ! -x "$EUROOFFICE_RUNTIME" ]; then
    msg_box "crun was not found at ${EUROOFFICE_RUNTIME}."
    exit 1
fi

choose_action

# For uninstall, discover the data directory first so the preservation notice
# names the correct location.
detect_nextcloud_settings || exit 1

if [ "$ACTION" = "uninstall" ]; then
    uninstall_eurooffice
    exit 0
fi

if [ "$ACTION" = "reinstall" ]; then
    FORCE_RECREATE=true
fi

if [ "$ACTION" = "install" ]; then
    install_popup "$SCRIPT_NAME"
fi

# --------------------------------------------------
# Compatibility checks
# --------------------------------------------------

if does_this_docker_exist 'collabora/code'; then
    msg_box "Collabora was detected. It may conflict with EuroOffice."
    if yesno_box_yes "Do you want to remove Collabora?"; then
        remove_collabora_docker
    fi
fi

if [ "$(apache2ctl -M 2>/dev/null | grep evasive)" != "" ]; then
    msg_box "mod_evasive may interfere with EuroOffice."
    if yesno_box_yes "Do you want to disable DDOS protection?"; then
        a2dismod evasive
        apt-get purge libapache2-mod-evasive -y
        systemctl restart apache2
    fi
fi

# --------------------------------------------------
# Configure network defaults
# --------------------------------------------------

DETECTED_IP="$(detect_local_ip)"
if [ -z "$DETECTED_IP" ]; then
    msg_box "Unable to detect a local IPv4 address. Enter a valid address manually."
fi

configure_network "$DETECTED_IP" || exit 1

# --------------------------------------------------
# Check Nextcloud
# --------------------------------------------------

print_text_in_color "$ICyan" "Checking Nextcloud..."

if ! curl -fsS "${NC_URL}/status.php" | grep -q '"installed":true'; then
    msg_box "Nextcloud is not installed or HTTPS is unavailable: ${NC_URL}"
    exit 1
fi

check_nextcloud_https "EuroOffice (Podman)"
ram_check 2 EuroOffice
cpu_check 2 EuroOffice

print_text_in_color "$IGreen" "EuroOffice backend: ${EUROOFFICE_INTERNAL_URL}"
print_text_in_color "$IGreen" "EuroOffice public URL: ${EUROOFFICE_PUBLIC_URL}"

# --------------------------------------------------
# Preserve or generate JWT secret
# --------------------------------------------------

print_text_in_color "$ICyan" "Checking existing JWT configuration..."

if EUROOFFICE_SECRET=$(
    sudo -u www-data php /var/www/nextcloud/occ \
        config:app:get eurooffice jwt_secret 2>/dev/null
); then
    if [[ ! "$EUROOFFICE_SECRET" =~ ^[a-zA-Z0-9_-]{32,}$ ]]; then
        EUROOFFICE_SECRET=""
    fi
fi

if [ -z "$EUROOFFICE_SECRET" ]; then
    EUROOFFICE_SECRET="$(openssl rand -hex 32)" || exit 1
fi

# --------------------------------------------------
# Pull latest image
# --------------------------------------------------

OLD_IMAGE_ID=""
if podman_image_exists "$EUROOFFICE_IMAGE"; then
    OLD_IMAGE_ID="$(get_image_id "$EUROOFFICE_IMAGE")"
fi

OLD_CONTAINER_IMAGE_ID=""
if podman_container_exists "$EUROOFFICE_CONTAINER"; then
    OLD_CONTAINER_IMAGE_ID="$(get_container_image_id "$EUROOFFICE_CONTAINER")"
fi

print_text_in_color "$ICyan" "Pulling latest EuroOffice image..."
if ! podman_crun pull "$EUROOFFICE_IMAGE"; then
    msg_box "Unable to download the EuroOffice image."
    exit 1
fi

NEW_IMAGE_ID="$(get_image_id "$EUROOFFICE_IMAGE")"
if [ -z "$NEW_IMAGE_ID" ]; then
    msg_box "Unable to determine the downloaded image ID."
    exit 1
fi

# --------------------------------------------------
# Determine whether recreation is required
# --------------------------------------------------

RECREATE_CONTAINER="$FORCE_RECREATE"

if ! podman_container_exists "$EUROOFFICE_CONTAINER"; then
    RECREATE_CONTAINER=true
else
    CURRENT_ENV="$(
        podman_crun inspect "$EUROOFFICE_CONTAINER" \
            --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null
    )"
    CURRENT_PORTS="$(podman_crun port "$EUROOFFICE_CONTAINER" 80/tcp 2>/dev/null)"
    EXPECTED_PORT="${EUROOFFICE_BIND_IP}:${EUROOFFICE_PORT}"

    if [ "$OLD_CONTAINER_IMAGE_ID" != "$NEW_IMAGE_ID" ]; then
        RECREATE_CONTAINER=true
    fi

    if ! printf '%s\n' "$CURRENT_PORTS" | grep -Fxq "$EXPECTED_PORT"; then
        RECREATE_CONTAINER=true
    fi

    if ! printf '%s\n' "$CURRENT_ENV" | grep -Fqx "JWT_SECRET=${EUROOFFICE_SECRET}"; then
        RECREATE_CONTAINER=true
    fi
    if ! printf '%s\n' "$CURRENT_ENV" | grep -Fqx "JWT_HEADER=${EUROOFFICE_JWT_HEADER}"; then
        RECREATE_CONTAINER=true
    fi
    if ! printf '%s\n' "$CURRENT_ENV" | grep -Fqx "JWT_ENABLED=true"; then
        RECREATE_CONTAINER=true
    fi
    if ! container_running; then
        RECREATE_CONTAINER=true
    fi

    # Recreate if persistent mount locations differ from the detected data path.
    CURRENT_MOUNTS="$(podman_crun inspect "$EUROOFFICE_CONTAINER" \
        --format '{{range .Mounts}}{{println .Source "=>" .Destination}}{{end}}' 2>/dev/null)"
    if ! printf '%s\n' "$CURRENT_MOUNTS" |
        grep -Fq "${EUROOFFICE_DATA_DIR}/data => /var/lib/euro-office/documentserver"; then
        RECREATE_CONTAINER=true
    fi
    if ! printf '%s\n' "$CURRENT_MOUNTS" |
        grep -Fq "${EUROOFFICE_DATA_DIR}/config => /etc/euro-office/documentserver"; then
        RECREATE_CONTAINER=true
    fi
    if ! printf '%s\n' "$CURRENT_MOUNTS" |
        grep -Fq "${EUROOFFICE_DATA_DIR}/runtime => /var/www/euro-office/Data"; then
        RECREATE_CONTAINER=true
    fi
fi

# --------------------------------------------------
# Create or recreate container
# --------------------------------------------------

if [ "$RECREATE_CONTAINER" = true ]; then
    print_text_in_color "$ICyan" "Creating/recreating EuroOffice container..."

    prepare_eurooffice_volumes || exit 1

    if podman_container_exists "$EUROOFFICE_CONTAINER"; then
        podman_crun rm -f "$EUROOFFICE_CONTAINER" >/dev/null 2>&1 || {
            msg_box "Unable to remove the existing EuroOffice container."
            exit 1
        }
    fi

    # Remove legacy Docker container if present.
    if command -v docker >/dev/null 2>&1; then
        docker rm -f "$EUROOFFICE_CONTAINER" >/dev/null 2>&1 || true
    fi

    if ! podman_crun run -d \
        --name "$EUROOFFICE_CONTAINER" \
        -p "${EUROOFFICE_BIND_IP}:${EUROOFFICE_PORT}:80" \
        -v "${EUROOFFICE_DATA_DIR}/data:/var/lib/euro-office/documentserver" \
        -v "${EUROOFFICE_DATA_DIR}/config:/etc/euro-office/documentserver" \
        -v "${EUROOFFICE_DATA_DIR}/runtime:/var/www/euro-office/Data" \
        -e JWT_ENABLED=true \
        -e JWT_HEADER="$EUROOFFICE_JWT_HEADER" \
        -e JWT_SECRET="$EUROOFFICE_SECRET" \
        --restart=always \
        "$EUROOFFICE_IMAGE"; then
        msg_box "EuroOffice container failed to start. Check Podman logs."
        exit 1
    fi
else
    print_text_in_color "$IGreen" "Image and configuration are up to date; no recreation required."
    if ! container_running; then
        podman_crun start "$EUROOFFICE_CONTAINER" || exit 1
    fi
fi

# --------------------------------------------------
# Install/update Nextcloud connector
# --------------------------------------------------

EUROOFFICE_APP_DIR="$(find /var/www/nextcloud \
    -type d -name eurooffice -print -quit 2>/dev/null)"

if [ -n "$EUROOFFICE_APP_DIR" ]; then
    print_text_in_color "$ICyan" "Updating Nextcloud EuroOffice connector..."
    nextcloud_occ app:update eurooffice || \
        print_text_in_color "$ICyan" "Connector update unavailable; keeping installed version."
    nextcloud_occ app:enable eurooffice || exit 1
else
    print_text_in_color "$ICyan" "Installing Nextcloud EuroOffice connector..."
    install_and_enable_app eurooffice
    EUROOFFICE_APP_DIR="$(find /var/www/nextcloud \
        -type d -name eurooffice -print -quit 2>/dev/null)"
fi

if [ -z "$EUROOFFICE_APP_DIR" ]; then
    msg_box "Nextcloud EuroOffice app installation failed."
    exit 1
fi

chown -R www-data:www-data "$EUROOFFICE_APP_DIR"

# --------------------------------------------------
# Configure Nextcloud connector
# --------------------------------------------------

print_text_in_color "$ICyan" "Configuring Nextcloud..."

nextcloud_occ config:app:set eurooffice DocumentServerUrl \
    --value="$EUROOFFICE_PUBLIC_URL"
nextcloud_occ config:app:set eurooffice DocumentServerInternalUrl \
    --value="$EUROOFFICE_INTERNAL_URL"
nextcloud_occ config:app:set eurooffice StorageUrl \
    --value="${NC_URL}/"
nextcloud_occ config:app:set eurooffice jwt_secret \
    --value="$EUROOFFICE_SECRET"
nextcloud_occ config:app:set eurooffice jwt_header \
    --value="$EUROOFFICE_JWT_HEADER"
nextcloud_occ config:system:set allow_local_remote_servers \
    --type=boolean --value=true

chown -R www-data:www-data "$EUROOFFICE_APP_DIR"

# --------------------------------------------------
# Healthcheck
# --------------------------------------------------

print_text_in_color "$ICyan" "Waiting for EuroOffice initialization..."
EUROOFFICE_HEALTHY=false

for attempt in $(seq 1 30); do
    if ! container_running; then
        print_text_in_color "$IRed" "EuroOffice container stopped unexpectedly."
        break
    fi

    if curl -fsS \
        "http://${EUROOFFICE_BIND_IP}:${EUROOFFICE_PORT}/healthcheck" \
        2>/dev/null | grep -qi true; then
        EUROOFFICE_HEALTHY=true
        break
    fi
    sleep 5
done

if [ "$EUROOFFICE_HEALTHY" != true ]; then
    echo "EuroOffice container logs:"
    podman_crun logs --tail 150 "$EUROOFFICE_CONTAINER"
    msg_box "EuroOffice healthcheck failed.

Check logs with:
podman --runtime /usr/bin/crun logs eurooffice"
    exit 1
fi

print_text_in_color "$IGreen" "EuroOffice healthcheck successful."

# --------------------------------------------------
# Nextcloud connection test
# --------------------------------------------------

print_text_in_color "$ICyan" "Testing Nextcloud connection to EuroOffice..."

if nextcloud_occ eurooffice:documentserver --check; then
    msg_box "EuroOffice installation/update completed successfully.

Public URL:
${EUROOFFICE_PUBLIC_URL}

Internal EuroOffice URL:
${EUROOFFICE_INTERNAL_URL}

Nextcloud storage URL:
${NC_URL}/

JWT header:
${EUROOFFICE_JWT_HEADER}

EuroOffice is operational."
else
    msg_box "EuroOffice container is running, but the Nextcloud connection test failed.

Check the Nextcloud and EuroOffice logs."
    exit 1
fi

exit 0
