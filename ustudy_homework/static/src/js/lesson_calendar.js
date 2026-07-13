/*
 * Portal "Mening Vazifalarim" calendar (/my/lessons/calendar).
 * Renders the student's lessons with FullCalendar (global build, bundled by
 * the web addon). Events are passed as JSON in #lesson_calendar[data-events]
 * by the controller. Plain IIFE (no odoo.define) so it runs on the public
 * website bundle without the module loader.
 */
(function () {
    "use strict";

    function initLessonCalendar() {
        var el = document.getElementById("lesson_calendar");
        if (!el) {
            return;
        }
        if (typeof FullCalendar === "undefined") {
            el.innerHTML = "<p class='text-danger mb-0'>Kalendar kutubxonasi yuklanmadi.</p>";
            return;
        }

        var events = [];
        try {
            events = JSON.parse(el.dataset.events || "[]");
        } catch (e) {
            events = [];
        }

        el.innerHTML = "";

        var calendar = new FullCalendar.Calendar(el, {
            initialView: "dayGridMonth",
            height: "auto",
            firstDay: 1,
            headerToolbar: {
                left: "prev,next today",
                center: "title",
                right: "dayGridMonth,dayGridWeek,listMonth",
            },
            buttonText: {
                today: "Bugun",
                month: "Oy",
                week: "Hafta",
                list: "Ro'yxat",
            },
            eventDisplay: "block",
            events: events,
        });

        calendar.render();

        // Open on the month of the first lesson rather than today's month.
        if (events.length && events[0].start) {
            calendar.gotoDate(events[0].start);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initLessonCalendar);
    } else {
        initLessonCalendar();
    }
})();
