export const CALENDAR_DAY_START = 8 * 60;
export const CALENDAR_VISIBLE_HOURS = 13;
export const CALENDAR_VISIBLE_MINUTES = CALENDAR_VISIBLE_HOURS * 60;
export const CALENDAR_PX_PER_HOUR = 64;
export const CALENDAR_PX_PER_MINUTE = CALENDAR_PX_PER_HOUR / 60;

/** Height from duration, capped so blocks do not paint into the next event in the same lane. */
export function eventHeightPx(event, dayEvents) {
  const natural = (event.duration / 60) * CALENDAR_PX_PER_HOUR - 2;
  const nextInLane = dayEvents
    .filter(
      (other) =>
        other.layoutColumn === event.layoutColumn &&
        other.startMinutes > event.startMinutes,
    )
    .sort((a, b) => a.startMinutes - b.startMinutes)[0];
  if (!nextInLane) return Math.max(11, natural);
  const gapPx =
    (nextInLane.startMinutes - event.startMinutes) * CALENDAR_PX_PER_MINUTE - 3;
  return Math.max(11, Math.min(natural, gapPx));
}

export function eventTopPercent(event) {
  return Math.max(
    0,
    ((event.startMinutes - CALENDAR_DAY_START) / CALENDAR_VISIBLE_MINUTES) * 100,
  );
}

/** Height as % of the day column so events stay aligned when the grid stretches. */
export function eventHeightPercent(event, dayEvents) {
  const natural =
    ((event.duration || 60) / CALENDAR_VISIBLE_MINUTES) * 100;
  const nextInLane = dayEvents
    .filter(
      (other) =>
        other.layoutColumn === event.layoutColumn &&
        other.startMinutes > event.startMinutes,
    )
    .sort((a, b) => a.startMinutes - b.startMinutes)[0];
  // Keep a readable floor so short breaks / micro-tasks still show a title.
  const readableFloor = 2.4;
  if (!nextInLane) return Math.max(readableFloor, natural);
  const gapPct =
    ((nextInLane.startMinutes - event.startMinutes) / CALENDAR_VISIBLE_MINUTES) *
      100 -
    0.35;
  return Math.max(readableFloor, Math.min(natural, gapPct));
}

/** Lay out timed events in a day column (Teams / Outlook style). Overlaps become side-by-side lanes. */
export function layoutDayEvents(dayEvents) {
  if (!dayEvents?.length) return [];

  const items = dayEvents
    .map((event) => ({
      ...event,
      _start: event.startMinutes,
      _end: event.startMinutes + (event.duration || 60),
      _key: `${event.id ?? event.task_id ?? "event"}-${event.startMinutes}`,
    }))
    .sort((a, b) => a._start - b._start || b._end - b._start - (a._end - a._start));

  const groups = [];
  let group = [];

  const overlaps = (a, b) => a._start < b._end && b._start < a._end;

  for (const item of items) {
    if (!group.length || group.some((other) => overlaps(other, item))) {
      group.push(item);
    } else {
      groups.push(group);
      group = [item];
    }
  }
  if (group.length) groups.push(group);

  const layout = new Map();

  for (const cluster of groups) {
    const columnEnds = [];
    const sorted = [...cluster].sort((a, b) => a._start - b._start || (b._end - b._start) - (a._end - a._start));

    for (const item of sorted) {
      let column = 0;
      while (columnEnds[column] !== undefined && columnEnds[column] > item._start) column += 1;
      columnEnds[column] = item._end;
      layout.set(item._key, { column, columns: 0 });
    }

    const columns = columnEnds.length;
    for (const item of sorted) {
      layout.get(item._key).columns = columns;
    }
  }

  return items.map((item) => {
    const lane = layout.get(item._key) || { column: 0, columns: 1 };
    const { _start, _end, _key, ...event } = item;
    return {
      ...event,
      layoutColumn: lane.column,
      layoutColumns: lane.columns,
    };
  });
}
