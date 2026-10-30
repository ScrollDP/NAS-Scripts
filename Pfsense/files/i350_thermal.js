events.push(function() {

    $('.i350-thermal-widget[data-refresh-freq]').each(function() {

        var container = $(this);

        var panel = container.closest(
            '[id^="widget-i350_thermal"]'
        );

        var refreshFreq = parseInt(
            container.attr('data-refresh-freq'),
            10
        );

        if (isNaN(refreshFreq) || refreshFreq < 1) {
            refreshFreq = 5;
        }

        if (refreshFreq > 60) {
            refreshFreq = 60;
        }

        var widgetKey = container.attr('data-widget-key');

        if (!widgetKey) {
            return;
        }

        var ajaxObject = new Object();

        ajaxObject.name =
            "i350-thermal-" + Math.random();

        ajaxObject.url =
            "/widgets/widgets/i350_thermal.widget.php";

        ajaxObject.callback = function(data) {

            var currentWidget =
                panel.find('.i350-thermal-widget');

            if (currentWidget.length) {
                currentWidget.first().replaceWith(data);
            }
        };

        ajaxObject.parms = {
            ajax: "ajax",
            widgetkey: widgetKey
        };

        ajaxObject.freq = refreshFreq;

        register_ajax(ajaxObject);
    });
});
