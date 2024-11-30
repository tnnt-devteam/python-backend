function showLeaderboard(leaderboard) {
    // This function unhides the div with class "leaderboard" and id
    // "leaderboard-<leaderboard>" and hides all others.
    var boards = document.querySelectorAll("div.leaderboard-container")
    for (var b of boards) {
        // See also the HTML template where it relies on element ids matching
        // the values in the combo box
        if (b.id === "leaderboard-" + leaderboard) {
            b.style.display = "initial";
        }
        else {
            b.style.display = "none";
        }
    }
}

function changeLeaderboard(leaderboard) {
    // This function changes the selected leaderboard *and* updates
    // window.location.href, reloading the page in the process.
    // Discard old fragment
    var url = window.location.href.split("#")[0];
    var new_url = [url, leaderboard].join("#")
    window.location.href = new_url;
    // at this point the "hashchange" event is triggered, causing the
    // display to be updated to show the correct leaderboard
}

function prevNextBoard(forward) {
    /* This function moves to the previous or next board according to their
     * order in the combo box element. */
    var combobox = document.getElementById("boards-combobox");
    if (!forward && combobox.selectedIndex > 0) {
        combobox.selectedIndex--;
        changeLeaderboard(combobox.value);
    }
    else if (forward && combobox.selectedIndex + 1 < combobox.length) {
        combobox.selectedIndex++;
        changeLeaderboard(combobox.value);
    }
}

function setComboBoxValue(leaderboard) {
    var combobox = document.getElementById("boards-combobox");
    var combobox_index = [].filter.call(combobox.options, _ => true)
        .map(o => o.value).findIndex(x => x === leaderboard);
    combobox.selectedIndex = combobox_index;
}

function getUrlFragment() {
    // Get the current hash fragment, if any
    var parts = window.location.href.split("#")
    var fragment = null
    if (parts.length == 2) {
        fragment = parts[1]
    }
    return fragment;
}

function onLoadOrHashChange() {
    var fragment = getUrlFragment();
    var combobox = document.getElementById("boards-combobox");
    var leaderboard = null;

    if (fragment !== null) {
        setComboBoxValue(fragment);
        leaderboard = fragment;
    } else {
        leaderboard = combobox.value;
    }

    showLeaderboard(leaderboard);
}

document.addEventListener("DOMContentLoaded", function(event) {
    onLoadOrHashChange();
    var combobox = document.getElementById("boards-combobox");
    combobox.addEventListener("change", function(event) {
        changeLeaderboard(combobox.value);
    });

    // set up event listeners for moving between boards without directly using
    // the combobox
    document.getElementById("prev-board").addEventListener("click", function(event) {
        prevNextBoard(false);
    });
    document.getElementById("next-board").addEventListener("click", function(event) {
        prevNextBoard(true);
    });
    document.addEventListener("keydown", function(event) {
        if ((event.code === "ArrowLeft" || event.code === "ArrowRight")
            && document.activeElement === combobox) {
            // if the combo box is in focus, assume the arrow keys will change
            // it and fire a change event, so do nothing here, otherwise we skip
            // over a board
            return;
        }
        if (event.code == "KeyH" || event.code == "ArrowLeft") {
            prevNextBoard(false);
        }
        if (event.code == "KeyL" || event.code == "ArrowRight") {
            prevNextBoard(true);
        }
    });
});

window.addEventListener("hashchange", onLoadOrHashChange);
