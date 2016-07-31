# encoding=utf-8
import json
import cgi
import pytz

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, Response, abort,
)
from flask.ext.login import current_user
from jinja2.utils import urlize
from icalendar import Calendar, Event
from slugify import slugify_unicode as slugify

from main import db

from .common import feature_flag
from models.cfp import Proposal, Venue
from models.ical import CalendarSource, CalendarEvent
from .schedule_xml import export_frab

schedule = Blueprint('schedule', __name__)

event_tz = pytz.timezone('Europe/London')


def _get_proposal_dict(proposal, favourites_ids):
    res = {
        'id': proposal.id,
        'start_date': event_tz.localize(proposal.scheduled_time),
        'end_date': event_tz.localize(proposal.end_date),
        'venue': proposal.venue.name,
        'title': proposal.title,
        'speaker': proposal.published_names or proposal.user.name,
        'description': proposal.description,
        'type': proposal.type,
        'may_record': proposal.may_record,
        'is_fave': proposal.id in favourites_ids,
        'source': 'database',
        'link': url_for('.line_up_proposal', proposal_id=proposal.id),
    }
    if proposal.type == 'workshop':
        res['cost'] = proposal.cost
    return res

def _get_ical_dict(event, favourites_ids):
    return {
        'id': event.uid,
        'start_date': event.start_dt,
        'end_date': event.end_dt,
        'venue': event.location or '(Unknown)',
        'title': event.summary,
        'speaker': '',
        'description': event.description,
        'type': 'talk',
        'may_record': False,
        'is_fave': event.id in favourites_ids,
        'source': 'external',
        'link': url_for('.line_up_external', event_id=event.id),
    }

def _get_scheduled_proposals(filter_obj={}):
    if current_user.is_anonymous():
        proposal_favourites = external_favourites = []
    else:
        proposal_favourites = [f.id for f in current_user.favourites]
        external_favourites = [f.id for f in current_user.calendar_favourites]

    schedule = Proposal.query.filter(Proposal.state.in_(['accepted', 'finished']),
                                      Proposal.scheduled_time.isnot(None),
                                      Proposal.scheduled_venue.isnot(None),
                                      Proposal.scheduled_duration.isnot(None)
                                    ).all()

    schedule = [_get_proposal_dict(p, proposal_favourites) for p in schedule]

    ical_sources = CalendarSource.query.filter_by(enabled=True)

    for source in ical_sources:
        for e in source.events:
            d = _get_ical_dict(e, external_favourites)
            # Override venue if we have a venue set on the source
            if source.main_venue:
                d['venue'] = source.main_venue
            else:
                d['venue'] = e.location
            schedule.append(d)

    if 'is_favourite' in filter_obj and filter_obj['is_favourite']:
        schedule = [s for s in schedule if s.get('is_fave', False)]

    if 'venue' in filter_obj:
        schedule = [s for s in schedule if s['venue'].name in filter_obj['venue']]

    return schedule

def _get_priority_sorted_venues(venues_to_allow):
    main_venues = Venue.query.filter().all()
    main_venues = sorted(main_venues, key=lambda x: x.priority)
    main_venues.reverse()
    main_venue_names = [v.name for v in main_venues]

    ical_sources = CalendarSource.query.filter_by(enabled=True)
    ical_sources = sorted(ical_sources, key=lambda x: x.priority)
    ical_sources.reverse()
    ical_source_names = [v.main_venue for v in ical_sources]

    # List event venues that are not overridden with zero priority
    for source in ical_sources:
        for e in source.events:
            if not source.main_venue:
                ical_source_names.append(e['location'])

    names = []
    for name_list in (main_venue_names, ical_source_names):
        for name in name_list:
            if name not in names and name in venues_to_allow:
                names.append(name)
    return names

@schedule.route('/schedule')
@feature_flag('SCHEDULE')
def main():
    def add_event(event):
        event['text'] = cgi.escape(event['title'])
        event['description'] = urlize(event['description'])
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        event['venue'] = slugify(event['venue'])
        return event

    # {id:1, text:"Meeting",   start_date:"04/11/2013 14:00",end_date:"04/11/2013 17:00"}
    schedule_data = _get_scheduled_proposals()

    venues_with_events = set([e['venue'] for e in schedule_data])
    venues = _get_priority_sorted_venues(venues_with_events)
    venues = [{'key': slugify(v), 'label': v} for v in venues]

    schedule_data = [add_event(e) for e in schedule_data]

    return render_template('schedule/user_schedule.html', venues=venues,
                            schedule_data=schedule_data)


@schedule.route('/schedule.json')
@feature_flag('SCHEDULE')
def schedule_json():
    def convert_time_to_str(event):
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        return event

    schedule = [convert_time_to_str(p) for p in _get_scheduled_proposals(request.args)]

    # NB this is JSON in a top-level array (security issue for low-end browsers)
    return Response(json.dumps(schedule), mimetype='application/json')

@schedule.route('/schedule.frab')
@feature_flag('SCHEDULE')
def schedule_frab():
    schedule = export_frab(_get_scheduled_proposals(request.args))

    return Response(schedule, mimetype='application/xml')

@schedule.route('/schedule.ical')
@feature_flag('SCHEDULE')
def schedule_ical():
    schedule = _get_scheduled_proposals(request.args)
    title = 'EMF 2016'

    cal = Calendar()
    cal.add('summary', title)
    cal.add('X-WR-CALNAME', title)
    cal.add('X-WR-CALDESC', title)
    cal.add('version', '2.0')

    for event in schedule:
        cal_event = Event()
        cal_event.add('uid', event['id'])
        cal_event.add('summary', event['title'])
        cal_event.add('location', event['venue'])
        cal_event.add('dtstart', event['start_date'])
        cal_event.add('dtend', event['end_date'])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype='text/calendar')

@schedule.route('/line-up')
@feature_flag('SCHEDULE')
def line_up_redirect():
    return redirect(url_for('.line_up'))

@schedule.route('/line-up/2016')
@feature_flag('SCHEDULE')
def line_up():
    proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
        filter(Proposal.state.in_(['accepted', 'finished'])).\
        filter(Proposal.type.in_(['talk', 'workshop'])).all()

    externals = CalendarSource.get_enabled_events()

    return render_template('schedule/line-up.html', proposals=proposals, externals=externals)


@schedule.route('/favourites')
@feature_flag('SCHEDULE')
def favourites():
    if current_user.is_anonymous():
        return redirect(url_for('users.login', next=url_for('.favourites')))

    proposals = current_user.favourites
    externals = current_user.calendar_favourites

    return render_template('schedule/favourites.html', proposals=proposals, externals=externals)

@schedule.route('/line-up/2016/<int:proposal_id>', methods=['GET', 'POST'])
@schedule.route('/line-up/2016/<int:proposal_id>-<slug>', methods=['GET', 'POST'])
@feature_flag('SCHEDULE')
def line_up_proposal(proposal_id, slug=None):
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.state not in ('accepted', 'finished'):
        abort(404)

    if slug != proposal.slug:
        return redirect(url_for('.line_up_proposal', proposal_id=proposal.id, slug=proposal.slug))

    if not current_user.is_anonymous():
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

    if (request.method == "POST") and not current_user.is_anonymous():
        if is_fave:
            current_user.favourites.remove(proposal)
            msg = 'Removed "%s" from favourites' % proposal.title
        else:
            current_user.favourites.append(proposal)
            msg = 'Added "%s" to favourites' % proposal.title
        db.session.commit()
        flash(msg)
        return redirect(url_for('.line_up_proposal', proposal_id=proposal.id, slug=proposal.slug))

    venue_name = None
    if proposal.scheduled_venue:
        venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

    return render_template('schedule/line-up-proposal.html',
                           proposal=proposal, is_fave=is_fave, venue_name=venue_name)

@schedule.route('/line-up/2016/external/<int:event_id>', methods=['GET', 'POST'])
@schedule.route('/line-up/2016/external/<int:event_id>-<slug>', methods=['GET', 'POST'])
@feature_flag('SCHEDULE')
def line_up_external(event_id, slug=None):
    event = CalendarEvent.query.get_or_404(event_id)

    if slug != event.slug:
        return redirect(url_for('.line_up_external', event_id=event.id, slug=event.slug))

    if not current_user.is_anonymous():
        is_fave = event in current_user.calendar_favourites
    else:
        is_fave = False

    if (request.method == "POST") and not current_user.is_anonymous():
        if is_fave:
            current_user.calendar_favourites.remove(event)
            msg = 'Removed "%s" from favourites' % event.title
        else:
            current_user.calendar_favourites.append(event)
            msg = 'Added "%s" to favourites' % event.title
        db.session.commit()
        flash(msg)
        return redirect(url_for('.line_up_external', event_id=event.id, slug=event.slug))

    return render_template('schedule/line-up-external.html',
                           event=event, is_fave=is_fave, venue_name=event.venue)
