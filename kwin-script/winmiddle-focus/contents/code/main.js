/* winmiddle-focus — push active window + cursor pos + panel hit to winmiddle */
function isPanelWindow(window) {
    if (!window) {
        return false;
    }
    try {
        if (window.dock || window.desktop || window.specialWindow) {
            return true;
        }
    } catch (e) {}
    var resourceClass = window.resourceClass ? String(window.resourceClass).toLowerCase() : "";
    return resourceClass.indexOf("plasmashell") !== -1;
}

function windowUnderCursor(pos) {
    try {
        if (!workspace.windowAt) {
            return null;
        }
        var hits = workspace.windowAt(pos, 1);
        if (!hits) {
            return null;
        }
        // QList may look like an array-like object in the script engine.
        if (hits.length !== undefined) {
            return hits.length > 0 ? hits[0] : null;
        }
        return hits;
    } catch (e) {
        return null;
    }
}

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
    var underPanel = isPanelWindow(windowUnderCursor(pos));
    callDBus(
        "local.winmiddle.Focus1",
        "/Focus",
        "local.winmiddle.FocusHub",
        "Update",
        resourceClass,
        resourceName,
        x,
        y,
        underPanel
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
