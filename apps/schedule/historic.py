""" View helpers for displaying historic schedules.

    These are served from static files in this repository as the database is wiped every year.
"""
import os
import csv
from flask import render_template, abort, redirect, url_for

from models.cfp import proposal_slug
from ..common import load_archive_file


def talks_historic(year):
    """ Handler to dispatch to the correct function.

        Archived schedules from 2012 - 2014 are in a different format and we haven't
        had the energy to convert them yet.
    """
    if year < 2012:
        abort(404)
    elif year == 2012:
        return talks_2012()
    elif year == 2013:
        return talks_2013()
    elif year == 2014:
        return talks_2014()
    else:
        return talks_previous(year)


def item_historic(year, proposal_id, slug):
    """ Handler to display a detail page for a schedule item."""
    if year < 2016:
        # Not showing details for old-format schedules at this time.
        abort(404)

    #  We might want to look at performance here but I'm not sure it's a huge issue at the moment
    data = load_archive_file(year, "public", "schedule.json")
    for item in data:
        if item["id"] == proposal_id:
            break
    else:
        abort(404)

    correct_slug = proposal_slug(item["title"])
    if slug != correct_slug:
        return redirect(
            url_for(".item", year=year, proposal_id=proposal_id, slug=correct_slug)
        )

    return render_template("schedule/historic/item.html", proposal=item)


def talks_previous(year):
    data = load_archive_file(year, "public", "schedule.json")
    stage_venues = ["Stage A", "Stage B", "Stage C"]
    workshop_venues = ["Workshop 1", "Workshop 2", "Workshop 3"]

    stage_events = []
    workshop_events = []

    for event in data:
        if event["source"] == "external":
            continue

        # Hack to remove Stitch's "hilarious" failed <script>
        if "<script>" in event["speaker"]:
            event["speaker"] = event["speaker"][
                0 : event["speaker"].find("<script>")
            ]  # "Some idiot"

        # All official (non-external) content is on a stage or workshop, so we don't care about anything that isn't
        if event["venue"] in stage_venues:
            events_list = stage_events
        elif event["venue"] in workshop_venues:
            events_list = workshop_events
        else:
            continue

        # Make sure it's not already in the list (basically repeated workshops)
        if not any(e["title"] == event["title"] for e in events_list):
            events_list.append(event)

    # Sort should avoid leading punctuation and whitespace and be case-insensitive
    stage_events.sort(key=lambda event: event["title"].strip().strip("'").upper())
    workshop_events.sort(key=lambda event: event["title"].strip().strip("'").upper())

    venues = [
        {"name": "Main Stages", "events": stage_events},
        {"name": "Workshops", "events": workshop_events},
    ]

    return render_template("schedule/historic/talks.html", venues=venues, year=year)


def talks_2014():
    data = load_archive_file(2014, "events.json")
    talks = []
    for event in data["conference_events"]["events"]:
        if event["type"] not in ("lecture", "workshop", "other"):
            continue
        talks.append(
            (
                ", ".join(
                    map(lambda speaker: speaker["full_public_name"], event["speakers"])
                ),
                event["title"],
                event["abstract"],
            )
        )

    return render_template("schedule/historic/talks-2014.html", talks=talks)


def talks_2013():
    data = load_archive_file(2013, "emw-talks.json")
    return render_template("schedule/historic/talks-2013.html", venues=data["stages"])


def talks_2012():
    days = {}
    talk_path = os.path.abspath(
        os.path.join(__file__, "..", "..", "..", "exports", "2012")
    )
    for day in ("friday", "saturday", "sunday"):
        reader = csv.reader(open(os.path.join(talk_path, "%s.csv" % day), "r"))
        rows = []
        for row in reader:
            cells = ["" if c == '"' else c for c in row]
            rows.append(cells)

        days[day] = rows

    return render_template("schedule/historic/talks-2012.html", **days)