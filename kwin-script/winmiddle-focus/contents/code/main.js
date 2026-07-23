/* winmiddle-focus — push active window + cursor pos to the winmiddle daemon */
function pushState() {
    var window = workspace.activeWindow;
    var pos = workspace.cursorPos;
    var resourceClass = "";
    var resourceName = "";
    if (window) {
        resourceClass = window.resourceClass ? String(window.resourceClass) : "";
        resourceName = window.resourceName ? String(window.resourceName) : "";
    }
    var x = pos ? pos.x : 0;
    var y = pos ? pos.y : 0;
    callDBus(
        "local.winmiddle.Focus1",
        "/Focus",
        "local.winmiddle.FocusHub",
        "Update",
        resourceClass,
        resourceName,
        x,
        y
    );
}

var timer = new QTimer();
timer.interval = 50;
timer.timeout.connect(pushState);
timer.start();

if (workspace.windowActivated) {
    workspace.windowActivated.connect(pushState);
}

pushState();
