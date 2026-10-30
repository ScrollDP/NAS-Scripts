<?php

require_once("guiconfig.inc");
require_once("functions.inc");
/*
 * Validate the dashboard widget key.
 *
 * pfSense supplies $widgetkey when the widget is included
 * from the dashboard. It is also supplied during configuration
 * form submissions and AJAX requests.
 */

/*
*if ($_POST['widgetkey'] || $_GET['widgetkey']) {
*    $rwidgetkey = isset($_POST['widgetkey'])
*        ? $_POST['widgetkey']
*        : (isset($_GET['widgetkey']) ? $_GET['widgetkey'] : null);
*
*    if (is_valid_widgetkey($rwidgetkey, $user_settings, __FILE__)) {
*        $widgetkey = $rwidgetkey;
*    } else {
*        print gettext("Invalid Widget Key");
*        exit;
*    }
*}
*/

if (
    isset($_REQUEST['widgetkey']) &&
    $_REQUEST['widgetkey'] !== ''
) {
    $rwidgetkey = $_REQUEST['widgetkey'];

    if (is_valid_widgetkey($rwidgetkey, $user_settings, __FILE__)) {
        $widgetkey = $rwidgetkey;
    } else {
        print gettext("Invalid Widget Key");
        exit;
    }
}


/*
 * Intel I350 Thermal Dashboard Widget
 *
 * Reads:
 *     /var/run/i350-thermal.json
 *
 * Hardware access is performed by:
 *     /usr/local/bin/i350-thermal
 *
 * The dashboard widget never accesses PCI hardware directly.
 */

$cache_file = "/var/run/i350-thermal.json";

/*
 * Get the configured service polling interval.
 *
 * The dashboard uses the same interval so it does not poll
 * the widget more frequently than the thermal monitor itself.
 */
$poll_interval = config_get_path(
    "installedpackages/i350thermal/config/0/poll_interval",
    "5"
);

if (!is_numeric($poll_interval)) {
    $poll_interval = 5;
}

$poll_interval = (int)$poll_interval;

if ($poll_interval < 1) {
    $poll_interval = 1;
}

if ($poll_interval > 60) {
    $poll_interval = 60;
}

/*
 * Allow some margin before displaying "stale".
 */
$stale_after = max(
    15,
    ($poll_interval * 2) + 5
);


/*
 * Save dashboard widget configuration.
 *
 * These settings are shared with the I350 thermal monitoring
 * service/worker.
 */
if ($_POST['widgetkey'] && !isset($_REQUEST['ajax'])) {

    set_customwidgettitle($user_settings);

    $enable = isset($_POST['enable']) ? "1" : "0";

    $new_interval = isset($_POST['poll_interval'])
        ? trim($_POST['poll_interval'])
        : "5";

    if (!ctype_digit($new_interval)) {
        $new_interval = "5";
    }

    $new_interval = (int)$new_interval;

    if ($new_interval < 1) {
        $new_interval = 1;
    }

    if ($new_interval > 60) {
        $new_interval = 60;
    }

    config_set_path(
        "installedpackages/i350thermal/config/0/enable",
        $enable
    );

    config_set_path(
        "installedpackages/i350thermal/config/0/poll_interval",
        (string)$new_interval
    );

    write_config(
        gettext("Updated Intel I350 Thermal dashboard widget settings.")
    );

    /*
     * Restart the worker so the new interval/state takes effect
     * immediately rather than waiting for its next configuration read.
     *
    *mwexec("/usr/local/etc/rc.d/i350_thermal restart");
    */
    header("Location: /index.php");
    exit;
}

/*
 * Render the widget contents.
 */

function i350_thermal_render($widgetkey)
{
    global $cache_file, $stale_after, $poll_interval;

    $data = null;

    if (file_exists($cache_file) && is_readable($cache_file)) {
        $json = @file_get_contents($cache_file);

        if ($json !== false) {
            $data = json_decode($json, true);
        }
    }

    /*
     * Cache unavailable / invalid.
     */
    if (!is_array($data)) {
        ?>
        <div class="alert alert-warning" style="margin-bottom:0;">
            <i class="fa-solid fa-triangle-exclamation"></i>
            <?=gettext("Thermal data is not available.")?>
            <br>
            <small>
                <?=gettext("The i350_thermal service may not be running.")?>
            </small>
        </div>
        <?php
        return;
    }

    /*
     * Determine cache age.
     */
    $timestamp = isset($data['timestamp'])
        ? (int)$data['timestamp']
        : @filemtime($cache_file);

    $age = time() - $timestamp;

    if ($age < 0) {
        $age = 0;
    }

    $stale = ($age > $stale_after);

    /*
     * No I350 detected.
     */
    if (
        empty($data['adapters']) ||
        !is_array($data['adapters'])
    ) {
        ?>
        <div class="alert alert-info" style="margin-bottom:0;">
            <i class="fa-solid fa-circle-info"></i>
            <?=gettext("No Intel I350 adapter detected.")?>
        </div>

        <div class="text-muted small" style="margin-top:8px;">
            <?=htmlspecialchars(
                sprintf(
                    gettext("Last check: %d seconds ago"),
                    $age
                )
            )?>
        </div>
        <?php
        return;
    }

    /*
     * Render every physical I350 adapter.
     */
    foreach ($data['adapters'] as $adapter):

        $temperature = isset($adapter['temperature'])
            ? (int)$adapter['temperature']
            : null;

        $status = isset($adapter['status'])
            ? strtolower((string)$adapter['status'])
            : 'unknown';

        $valid = !empty($adapter['valid']);

        $thresholds = isset($adapter['thresholds']) &&
                      is_array($adapter['thresholds'])
            ? $adapter['thresholds']
            : array();

        $low = isset($thresholds['low'])
            ? (int)$thresholds['low']
            : null;

        $mid = isset($thresholds['mid'])
            ? (int)$thresholds['mid']
            : null;

        $high = isset($thresholds['high'])
            ? (int)$thresholds['high']
            : null;

        $interfaces = isset($adapter['interfaces']) &&
                      is_array($adapter['interfaces'])
            ? $adapter['interfaces']
            : array();

        /*
         * Status classes.
         */
        switch ($status) {
            case 'normal':
                $status_class = 'text-success';
                $status_icon = 'fa-circle-check';
                break;

            case 'warm':
                $status_class = 'text-warning';
                $status_icon = 'fa-temperature-half';
                break;

            case 'high':
                $status_class = 'text-warning';
                $status_icon = 'fa-triangle-exclamation';
                break;

            case 'critical':
                $status_class = 'text-danger';
                $status_icon = 'fa-circle-exclamation';
                break;

            default:
                $status_class = 'text-muted';
                $status_icon = 'fa-circle-question';
                break;
        }

        /*
         * Event helper.
         */
        $thermal_throttle = !empty($adapter['thermal_throttle']);
        $power_down       = !empty($adapter['power_down']);
        $low_event        = !empty($adapter['low_event']);
        $mid_event        = !empty($adapter['mid_event']);
        $high_event       = !empty($adapter['high_event']);

        ?>

        <div
            class="i350-thermal-widget"
            data-refresh-freq="<?=htmlspecialchars($poll_interval)?>"
            data-widget-key="<?=htmlspecialchars($widgetkey)?>"
        >
            <?php if ($stale): ?>

                <div class="alert alert-warning" style="margin-bottom:12px;">
                    <i class="fa-solid fa-clock"></i>
                    <?=gettext("Thermal data is stale.")?>
                    <small>
                        <?=htmlspecialchars(
                            sprintf(
                                gettext("Last update %d seconds ago."),
                                $age
                            )
                        )?>
                    </small>
                </div>

            <?php endif; ?>

            <div class="text-center" style="padding:8px 0 16px;">

                <?php if ($valid && $temperature !== null): ?>

                    <div
                        class="i350-temperature"
                        style="
                            font-size:42px;
                            line-height:1.1;
                            font-weight:600;
                        "
                    >
                        <?=htmlspecialchars($temperature)?> °C
                    </div>

                    <div
                        class="<?=$status_class?>"
                        style="
                            font-size:15px;
                            margin-top:6px;
                        "
                    >
                        <i class="fa-solid <?=$status_icon?>"></i>
                        <?=htmlspecialchars(ucfirst($status))?>
                    </div>

                <?php else: ?>

                    <div
                        class="text-muted"
                        style="
                            font-size:24px;
                            padding:10px;
                        "
                    >
                        <?=gettext("Sensor invalid")?>
                    </div>

                <?php endif; ?>

            </div>

            <table class="table table-condensed table-hover"
                   style="margin-bottom:10px;">

                <tbody>

                <tr>
                    <th style="width:42%;">
                        <?=gettext("PCI device")?>
                    </th>
                    <td>
                        <?=htmlspecialchars(
                            (string)($adapter['pci'] ?? 'Unknown')
                        )?>
                    </td>
                </tr>

                <tr>
                    <th>
                        <?=gettext("Sensor")?>
                    </th>
                    <td>
                        <?=htmlspecialchars(
                            (string)($adapter['sensor_interface'] ?? 'Unknown')
                        )?>
                    </td>
                </tr>

                <tr>
                    <th>
                        <?=gettext("Ports")?>
                    </th>
                    <td>
                        <?php if (!empty($interfaces)): ?>

                            <?php foreach ($interfaces as $interface): ?>

                                <span class="label label-default"
                                      style="display:inline-block;margin:2px;">
                                    <?=htmlspecialchars($interface)?>
                                </span>

                            <?php endforeach; ?>

                        <?php else: ?>

                            <span class="text-muted">
                                <?=gettext("None")?>
                            </span>

                        <?php endif; ?>
                    </td>
                </tr>

                </tbody>

            </table>


            <table class="table table-condensed table-hover"
                   style="margin-bottom:10px;">

                <thead>
                <tr>
                    <th colspan="2">
                        <?=gettext("Thermal thresholds")?>
                    </th>
                </tr>
                </thead>

                <tbody>

                <tr>
                    <th><?=gettext("Low")?></th>
                    <td>
                        <?=($low !== null)
                            ? htmlspecialchars($low) . " °C"
                            : "—"?>
                    </td>
                </tr>

                <tr>
                    <th><?=gettext("Mid")?></th>
                    <td>
                        <?=($mid !== null)
                            ? htmlspecialchars($mid) . " °C"
                            : "—"?>
                    </td>
                </tr>

                <tr>
                    <th><?=gettext("High")?></th>
                    <td>
                        <?=($high !== null)
                            ? htmlspecialchars($high) . " °C"
                            : "—"?>
                    </td>
                </tr>

                </tbody>

            </table>


            <table class="table table-condensed"
                   style="margin-bottom:8px;">

                <tbody>

                <tr>
                    <th>
                        <?=gettext("Thermal throttle")?>
                    </th>
                    <td class="text-right">
                        <?php if ($thermal_throttle): ?>

                            <span class="text-danger">
                                <i class="fa-solid fa-triangle-exclamation"></i>
                                <?=gettext("Yes")?>
                            </span>

                        <?php else: ?>

                            <span class="text-success">
                                <?=gettext("No")?>
                            </span>

                        <?php endif; ?>
                    </td>
                </tr>

                <tr>
                    <th>
                        <?=gettext("Power-down event")?>
                    </th>
                    <td class="text-right">
                        <?php if ($power_down): ?>

                            <span class="text-danger">
                                <?=gettext("Yes")?>
                            </span>

                        <?php else: ?>

                            <span class="text-success">
                                <?=gettext("No")?>
                            </span>

                        <?php endif; ?>
                    </td>
                </tr>

                <tr>
                    <th>
                        <?=gettext("Low event")?>
                    </th>
                    <td class="text-right">
                        <?=($low_event)
                            ? '<span class="text-warning">' .
                              gettext("Yes") .
                              '</span>'
                            : '<span class="text-muted">' .
                              gettext("No") .
                              '</span>'?>
                    </td>
                </tr>

                <tr>
                    <th>
                        <?=gettext("Mid event")?>
                    </th>
                    <td class="text-right">
                        <?=($mid_event)
                            ? '<span class="text-warning">' .
                              gettext("Yes") .
                              '</span>'
                            : '<span class="text-muted">' .
                              gettext("No") .
                              '</span>'?>
                    </td>
                </tr>

                <tr>
                    <th>
                        <?=gettext("High event")?>
                    </th>
                    <td class="text-right">
                        <?=($high_event)
                            ? '<span class="text-danger">' .
                              gettext("Yes") .
                              '</span>'
                            : '<span class="text-muted">' .
                              gettext("No") .
                              '</span>'?>
                    </td>
                </tr>

                </tbody>

            </table>


            <div class="text-muted small text-right">

                <?php if ($stale): ?>

                    <i class="fa-solid fa-clock"></i>
                    <?=htmlspecialchars(
                        sprintf(
                            gettext("Updated %d seconds ago"),
                            $age
                        )
                    )?>

                <?php else: ?>

                    <i class="fa-solid fa-circle-check"></i>
                    <?=htmlspecialchars(
                        sprintf(
                            gettext("Updated %d seconds ago"),
                            $age
                        )
                    )?>

                <?php endif; ?>

            </div>

        </div>

        <?php

    endforeach;
}


/*
 * AJAX refresh request.
 *
 * The pfSense dashboard has a centralized widget AJAX system.
 * Returning only the widget body avoids rebuilding the entire dashboard.
 */
if (
    isset($_REQUEST['ajax']) &&
    $_REQUEST['ajax'] === 'ajax'
) {
    i350_thermal_render($widgetkey);
    exit;
}


/*
 * Normal dashboard rendering.
 */
i350_thermal_render($widgetkey);
?>

</div><div id="<?=$widget_panel_footer_id?>" class="panel-footer collapse">

<form
    action="/widgets/widgets/i350_thermal.widget.php"
    method="post"
    class="form-horizontal"
>

    <?=gen_customwidgettitle_div($widgetconfig['title']); ?>

    <input
        type="hidden"
        name="widgetkey"
        value="<?=htmlspecialchars($widgetkey)?>"
    >

    <div class="panel panel-default col-sm-10">

        <div class="panel-body">

            <div class="form-group">
                <label class="col-sm-4 control-label">
                    <?=gettext("Enable")?>
                </label>

                <div class="col-sm-8">
                    <input
                        type="checkbox"
                        name="enable"
                        value="1"
                        <?=(
                            config_get_path(
                                "installedpackages/i350thermal/config/0/enable",
                                "1"
                            ) == "1"
                        ) ? "checked" : ""?>
                    >
                    <?=gettext("Enable Intel I350 thermal monitoring")?>

                    <span class="help-block">
                        <?=gettext(
                            "Enable background monitoring of Intel I350 thermal sensors."
                        )?>
                    </span>
                </div>
            </div>

            <div class="form-group">
                <label
                    for="i350_poll_interval"
                    class="col-sm-4 control-label"
                >
                    <?=gettext("Polling interval")?>
                </label>

                <div class="col-sm-8">

                    <input
                        type="number"
                        id="i350_poll_interval"
                        name="poll_interval"
                        value="<?=htmlspecialchars(
                            config_get_path(
                                "installedpackages/i350thermal/config/0/poll_interval",
                                "5"
                            )
                        )?>"
                        min="1"
                        max="60"
                        class="form-control"
                    >

                    <span class="help-block">
                        <?=gettext(
                            "How often the I350 thermal sensor is read."
                        )?>
                        <br>
                        <span class="text-danger"><?=gettext("Note:")?></span>
                        <?=gettext(
                            "The allowed range is 1 to 60 seconds."
                        )?>
                    </span>

                </div>
            </div>

        </div>

    </div>

    <div class="form-group">

        <div class="col-sm-offset-3 col-sm-6">

            <button
                type="submit"
                class="btn btn-primary"
            >
                <i class="fa-solid fa-save icon-embed-btn"></i>
                <?=gettext("Save")?>
            </button>

        </div>

    </div>

</form>

<?php
if (isset($_REQUEST['ajax']) && $_REQUEST['ajax'] === 'ajax') {
    exit;
}
?>
