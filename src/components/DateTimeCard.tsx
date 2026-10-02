import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Clock,
  Calendar as CalendarIcon,
  Globe,
  Sun,
  Moon,
  ChevronLeft,
  ChevronRight,
  Plus,
  Trash2,
  ExternalLink,
  RefreshCw,
  Users,
  CheckCircle2,
  CalendarCheck,
  Sparkles,
  X,
  Bell,
  Zap,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

interface CalendarEvent {
  id: string;
  summary: string;
  description?: string;
  start?: { dateTime?: string; date?: string; timeZone?: string };
  end?: { dateTime?: string; date?: string; timeZone?: string };
  htmlLink?: string;
  attendees?: Array<{ email: string; displayName?: string; responseStatus?: string }>;
}

export interface ScheduledTaskItem {
  id: string;
  name: string;
  description?: string | null;
  prompt: string;
  task_type: 'reminder' | 'automation';
  schedule_definition?: {
    frequency?: string;
    target_time?: string;
    time?: string;
  };
  next_run_at?: string | null;
  enabled: boolean;
}

interface DateTimeCardProps {
  userQuery?: string;
}

export const DateTimeCard: React.FC<DateTimeCardProps> = ({ userQuery = '' }) => {
  const { user } = useAuth();
  const [now, setNow] = useState(new Date());

  const queryLower = userQuery.toLowerCase();
  const prefersCalendar =
    !queryLower.includes('time') &&
    !queryLower.includes('clock') &&
    (
      queryLower.includes('date') ||
      queryLower.includes('calendar') ||
      queryLower.includes('day') ||
      queryLower.includes('today') ||
      queryLower.includes('month') ||
      queryLower.includes('meeting') ||
      queryLower.includes('schedule') ||
      queryLower.includes('event')
    );

  const [activeTab, setActiveTabState] = useState<'clock' | 'calendar'>(
    prefersCalendar ? 'calendar' : 'clock'
  );

  const setActiveTab = (tab: 'clock' | 'calendar') => {
    setActiveTabState(tab);
    setTimeout(() => {
      window.dispatchEvent(new Event('resize'));
    }, 10);
  };

  // Live ticking clock
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Time calculations
  const hours24 = now.getHours();
  const hours12 = (hours24 % 12 || 12).toString().padStart(2, '0');
  const minutes = now.getMinutes().toString().padStart(2, '0');
  const seconds = now.getSeconds().toString().padStart(2, '0');
  const ampm = hours24 >= 12 ? 'PM' : 'AM';
  const isDaytime = hours24 >= 6 && hours24 < 18;

  // Date calculations
  const weekday = now.toLocaleDateString('en-US', { weekday: 'long' });
  const monthLong = now.toLocaleDateString('en-US', { month: 'long' });
  const day = now.getDate();
  const year = now.getFullYear();

  // Timezone
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const tzOffsetMin = -now.getTimezoneOffset();
  const tzSign = tzOffsetMin >= 0 ? '+' : '-';
  const tzHours = Math.floor(Math.abs(tzOffsetMin) / 60).toString().padStart(2, '0');
  const tzMins = (Math.abs(tzOffsetMin) % 60).toString().padStart(2, '0');
  const tzOffsetStr = `UTC${tzSign}${tzHours}:${tzMins}`;

  // ── Calendar Events & Scheduled Tasks State & Integration ───────────────────
  const isTodayQuery = queryLower.includes('today') || queryLower.includes("today's") || queryLower.includes("todays");
  const isTomorrowQuery = queryLower.includes('tomorrow');

  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTaskItem[]>([]);
  const [agendaFilter, setAgendaFilter] = useState<'all' | 'calendar' | 'tasks'>('all');
  const [isConnected, setIsConnected] = useState(false);
  const [isLoadingEvents, setIsLoadingEvents] = useState(false);
  const [selectedDayNumber, setSelectedDayNumber] = useState<number | null>(() => {
    if (isTodayQuery) return new Date().getDate();
    if (isTomorrowQuery) {
      const tom = new Date();
      tom.setDate(tom.getDate() + 1);
      return tom.getDate();
    }
    return null;
  });
  const [calendarViewDate, setCalendarViewDate] = useState<Date>(new Date());

  useEffect(() => {
    if (isTodayQuery) {
      setSelectedDayNumber(now.getDate());
    } else if (isTomorrowQuery) {
      const tom = new Date();
      tom.setDate(tom.getDate() + 1);
      setSelectedDayNumber(tom.getDate());
    }
  }, [userQuery]);

  // Quick Add Event Form state
  const [isAddFormOpen, setIsAddFormOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDate, setNewDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().split('T')[0];
  });
  const [newTime, setNewTime] = useState('11:00');
  const [newDescription, setNewDescription] = useState('');
  const [isSubmittingEvent, setIsSubmittingEvent] = useState(false);
  const [formFeedback, setFormFeedback] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async () => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (user) {
      try {
        const token = await user.getIdToken();
        headers['Authorization'] = `Bearer ${token}`;
      } catch (_) {}
    }
    return headers;
  }, [user]);

  const loadCalendarEvents = useCallback(async () => {
    setIsLoadingEvents(true);
    try {
      const headers = await getAuthHeaders();
      const [calRes, taskRes] = await Promise.allSettled([
        fetch('http://127.0.0.1:8000/api/connectors/calendar/events?max_results=30', { headers }),
        fetch('http://127.0.0.1:8000/api/scheduled-tasks', { headers }),
      ]);

      if (calRes.status === 'fulfilled' && calRes.value.ok) {
        const data = await calRes.value.json();
        setIsConnected(Boolean(data.connected));
        if (data.events && Array.isArray(data.events)) {
          setEvents(data.events);
        }
      }

      if (taskRes.status === 'fulfilled' && taskRes.value.ok) {
        const tasksData = await taskRes.value.json();
        if (Array.isArray(tasksData)) {
          setScheduledTasks(tasksData.filter((t: any) => t.enabled !== false));
        }
      }
    } catch (err) {
      console.warn('Could not load calendar events or tasks:', err);
    } finally {
      setIsLoadingEvents(false);
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    loadCalendarEvents();
  }, [loadCalendarEvents]);

  // Calendar matrix calculations for calendarViewDate
  const viewYear = calendarViewDate.getFullYear();
  const viewMonth = calendarViewDate.getMonth();
  const viewMonthLong = calendarViewDate.toLocaleDateString('en-US', { month: 'long' });
  const firstDay = new Date(viewYear, viewMonth, 1).getDay();
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const calendarCells: (number | null)[] = useMemo(() => {
    const cells: (number | null)[] = [];
    for (let i = 0; i < firstDay; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    return cells;
  }, [firstDay, daysInMonth]);

  // Map events to days of the currently viewed month
  const eventsByDay = useMemo(() => {
    const map: Record<number, CalendarEvent[]> = {};
    events.forEach((ev) => {
      const rawDateStr = ev.start?.dateTime || ev.start?.date;
      if (!rawDateStr) return;
      const evDate = new Date(rawDateStr);
      if (evDate.getFullYear() === viewYear && evDate.getMonth() === viewMonth) {
        const dNum = evDate.getDate();
        if (!map[dNum]) map[dNum] = [];
        map[dNum].push(ev);
      }
    });
    return map;
  }, [events, viewYear, viewMonth]);

  // Map scheduled tasks to days of the currently viewed month
  const tasksByDay = useMemo(() => {
    const map: Record<number, ScheduledTaskItem[]> = {};
    scheduledTasks.forEach((t) => {
      const rawDateStr = t.next_run_at;
      if (!rawDateStr) return;
      const tDate = new Date(rawDateStr);
      if (tDate.getFullYear() === viewYear && tDate.getMonth() === viewMonth) {
        const dNum = tDate.getDate();
        if (!map[dNum]) map[dNum] = [];
        map[dNum].push(t);
      }
    });
    return map;
  }, [scheduledTasks, viewYear, viewMonth]);

  // Filter events based on selected date or show all upcoming
  const displayedEvents = useMemo(() => {
    if (selectedDayNumber === null) {
      return events;
    }
    return eventsByDay[selectedDayNumber] || [];
  }, [selectedDayNumber, events, eventsByDay]);

  // Filter tasks based on selected date or show all upcoming
  const displayedTasks = useMemo(() => {
    if (selectedDayNumber === null) {
      return scheduledTasks;
    }
    return tasksByDay[selectedDayNumber] || [];
  }, [selectedDayNumber, scheduledTasks, tasksByDay]);

  const handlePrevMonth = () => {
    setCalendarViewDate(new Date(viewYear, viewMonth - 1, 1));
    setSelectedDayNumber(null);
  };

  const handleNextMonth = () => {
    setCalendarViewDate(new Date(viewYear, viewMonth + 1, 1));
    setSelectedDayNumber(null);
  };

  const handleTodayClick = () => {
    const today = new Date();
    setCalendarViewDate(today);
    setSelectedDayNumber(today.getDate());
  };

  const handleCreateEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;

    setIsSubmittingEvent(true);
    setFormFeedback(null);
    try {
      const headers = await getAuthHeaders();
      const startDateTime = `${newDate}T${newTime}:00`;
      const res = await fetch('http://127.0.0.1:8000/api/connectors/calendar/events', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          summary: newTitle.trim(),
          start_time: startDateTime,
          description: newDescription.trim(),
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to create event');
      }

      setFormFeedback('Event scheduled successfully!');
      setNewTitle('');
      setNewDescription('');
      setIsAddFormOpen(false);
      await loadCalendarEvents();
      setTimeout(() => setFormFeedback(null), 3000);
    } catch (err: any) {
      setFormFeedback(err.message || 'Error creating event');
    } finally {
      setIsSubmittingEvent(false);
    }
  };

  const handleDeleteEvent = async (eventId: string, eventTitle: string) => {
    if (!window.confirm(`Are you sure you want to cancel '${eventTitle}'?`)) return;

    // Optimistic removal
    setEvents((prev) => prev.filter((ev) => ev.id !== eventId));
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`http://127.0.0.1:8000/api/connectors/calendar/events/${eventId}`, {
        method: 'DELETE',
        headers,
      });
      if (!res.ok) {
        await loadCalendarEvents();
      }
    } catch (err) {
      console.error('Delete event error:', err);
      await loadCalendarEvents();
    }
  };

  const formatEventTime = (ev: CalendarEvent) => {
    const raw = ev.start?.dateTime || ev.start?.date;
    if (!raw) return 'Scheduled';
    const d = new Date(raw);
    const isToday =
      d.getDate() === now.getDate() &&
      d.getMonth() === now.getMonth() &&
      d.getFullYear() === now.getFullYear();
    const isTomorrow =
      d.getDate() === now.getDate() + 1 &&
      d.getMonth() === now.getMonth() &&
      d.getFullYear() === now.getFullYear();

    const timeString = ev.start?.dateTime
      ? d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
      : 'All Day';

    if (isToday) return `Today at ${timeString}`;
    if (isTomorrow) return `Tomorrow at ${timeString}`;
    return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} at ${timeString}`;
  };

  const formatTaskTime = (task: ScheduledTaskItem) => {
    const raw = task.next_run_at;
    if (!raw) return 'Scheduled';
    const d = new Date(raw);
    const isToday =
      d.getDate() === now.getDate() &&
      d.getMonth() === now.getMonth() &&
      d.getFullYear() === now.getFullYear();
    const isTomorrow =
      d.getDate() === now.getDate() + 1 &&
      d.getMonth() === now.getMonth() &&
      d.getFullYear() === now.getFullYear();

    const timeString = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });

    if (isToday) return `Today at ${timeString}`;
    if (isTomorrow) return `Tomorrow at ${timeString}`;
    return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} at ${timeString}`;
  };

  return (
    <div className="rounded-2xl bg-gradient-to-b from-white/[0.08] to-white/[0.02] border border-white/12 p-4 text-neutral-200 shadow-2xl space-y-3.5 select-none transition-all">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between pb-2 border-b border-white/[0.08] gap-2 flex-wrap">
        <div className="flex items-center space-x-2">
          {activeTab === 'clock' ? (
            <div className="p-1.5 rounded-lg bg-blue-500/20 text-blue-300 border border-blue-500/30 shadow-sm shadow-blue-500/20">
              <Clock className="w-3.5 h-3.5" />
            </div>
          ) : (
            <div className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 shadow-sm shadow-indigo-500/20">
              <CalendarIcon className="w-3.5 h-3.5" />
            </div>
          )}
          <span className="text-xs font-semibold text-white tracking-wide">
            {activeTab === 'clock' ? 'System Clock' : 'Calendar & Schedule'}
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/10 text-neutral-300 border border-white/10">
            {timezone}
          </span>
        </div>

        {/* Tab switch */}
        <div className="flex items-center p-0.5 rounded-lg bg-black/40 border border-white/10 text-[11px] font-medium">
          <button
            onClick={() => setActiveTab('clock')}
            className={`px-2.5 py-1 rounded-md transition-all ${
              activeTab === 'clock'
                ? 'bg-blue-500/30 text-white font-medium shadow-sm border border-blue-500/40'
                : 'text-neutral-400 hover:text-white'
            }`}
          >
            Clock
          </button>
          <button
            onClick={() => setActiveTab('calendar')}
            className={`px-2.5 py-1 rounded-md transition-all ${
              activeTab === 'calendar'
                ? 'bg-indigo-500/30 text-white font-medium shadow-sm border border-indigo-500/40'
                : 'text-neutral-400 hover:text-white'
            }`}
          >
            Calendar
          </button>
        </div>
      </div>

      {/* CLOCK VIEW */}
      {activeTab === 'clock' ? (
        <div className="p-4 rounded-xl bg-black/40 border border-white/[0.08] space-y-3">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <div className="flex items-baseline space-x-1.5 font-mono">
              <span className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white">
                {hours12}:{minutes}
              </span>
              <span className="text-xl font-semibold text-blue-400">
                :{seconds}
              </span>
              <span className="ml-2 text-xs font-bold px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30 font-mono">
                {ampm}
              </span>
            </div>

            <div className="flex items-center space-x-1.5 text-xs text-neutral-400 font-sans">
              {isDaytime ? (
                <Sun className="w-4 h-4 text-amber-400" />
              ) : (
                <Moon className="w-4 h-4 text-blue-300" />
              )}
              <span>{isDaytime ? 'Daytime' : 'Night'}</span>
            </div>
          </div>

          <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-xs text-neutral-300 flex-wrap gap-2">
            <span className="font-medium text-white">
              {weekday}, {monthLong} {day}, {year}
            </span>
            <div className="flex items-center space-x-2 text-[11px] font-mono text-neutral-400">
              <span>24h: {hours24.toString().padStart(2, '0')}:{minutes}</span>
              <span>•</span>
              <span className="flex items-center space-x-1">
                <Globe className="w-3 h-3" />
                <span>{tzOffsetStr}</span>
              </span>
            </div>
          </div>
        </div>
      ) : (
        /* CALENDAR VIEW: Interactive Monthly Grid & Live Agenda */
        <div className="space-y-3">
          {/* Calendar Top Toolbar: Controls, Status & Add */}
          <div className="flex items-center justify-between gap-2 flex-wrap text-xs">
            {/* Month & Navigation */}
            <div className="flex items-center space-x-1.5">
              <button
                onClick={handlePrevMonth}
                className="p-1 rounded-md bg-white/[0.05] hover:bg-white/[0.12] text-neutral-300 hover:text-white border border-white/10 transition-all"
                title="Previous month"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="font-bold text-white px-1 tracking-wide text-xs">
                {viewMonthLong} {viewYear}
              </span>
              <button
                onClick={handleNextMonth}
                className="p-1 rounded-md bg-white/[0.05] hover:bg-white/[0.12] text-neutral-300 hover:text-white border border-white/10 transition-all"
                title="Next month"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={handleTodayClick}
                className="px-2 py-0.5 rounded-md bg-white/[0.05] hover:bg-white/[0.12] text-[10px] text-neutral-300 hover:text-white border border-white/10 font-mono transition-all ml-1"
              >
                Today
              </button>
            </div>

            {/* Status Indicator & Action Buttons */}
            <div className="flex items-center space-x-1.5">
              {isConnected ? (
                <div
                  className="flex items-center space-x-1 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-medium"
                  title="Google Calendar connected and synced"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span>Google Calendar</span>
                </div>
              ) : (
                <div className="flex items-center space-x-1 px-2 py-0.5 rounded-full bg-white/10 text-neutral-400 border border-white/10 text-[10px]">
                  <span>Local Mode</span>
                </div>
              )}

              <button
                onClick={loadCalendarEvents}
                disabled={isLoadingEvents}
                className={`p-1 rounded-md bg-white/[0.05] hover:bg-white/[0.12] text-neutral-300 hover:text-white border border-white/10 transition-all ${
                  isLoadingEvents ? 'opacity-50 cursor-not-allowed' : ''
                }`}
                title="Refresh events from calendar"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoadingEvents ? 'animate-spin text-sky-400' : ''}`} />
              </button>

              <button
                onClick={() => setIsAddFormOpen(!isAddFormOpen)}
                className="flex items-center space-x-1 px-2 py-1 rounded-md bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 hover:text-white border border-indigo-500/30 text-[11px] font-medium transition-all"
              >
                <Plus className="w-3 h-3" />
                <span>Add Event</span>
              </button>
            </div>
          </div>

          {/* Inline Quick Add Event Form */}
          {isAddFormOpen && (
            <form
              onSubmit={handleCreateEvent}
              className="p-3 rounded-xl bg-black/60 border border-indigo-500/30 space-y-2.5 shadow-lg text-xs"
            >
              <div className="flex items-center justify-between pb-1 border-b border-white/10">
                <div className="flex items-center space-x-1.5 text-indigo-300 font-semibold">
                  <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Schedule New Event</span>
                </div>
                <button
                  type="button"
                  onClick={() => setIsAddFormOpen(false)}
                  className="p-0.5 rounded text-neutral-400 hover:text-white"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <div>
                <input
                  type="text"
                  placeholder="Event title (e.g. Sync with Team)"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-white/[0.06] border border-white/15 text-white placeholder-neutral-500 focus:outline-none focus:border-indigo-400 text-xs"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[10px] text-neutral-400 mb-0.5 font-medium">Date</label>
                  <input
                    type="date"
                    value={newDate}
                    onChange={(e) => setNewDate(e.target.value)}
                    className="w-full px-2 py-1 rounded-md bg-white/[0.06] border border-white/15 text-white text-xs font-mono focus:outline-none focus:border-indigo-400"
                    required
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-neutral-400 mb-0.5 font-medium">Time</label>
                  <input
                    type="time"
                    value={newTime}
                    onChange={(e) => setNewTime(e.target.value)}
                    className="w-full px-2 py-1 rounded-md bg-white/[0.06] border border-white/15 text-white text-xs font-mono focus:outline-none focus:border-indigo-400"
                    required
                  />
                </div>
              </div>

              <div>
                <input
                  type="text"
                  placeholder="Description or notes (optional)"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  className="w-full px-2.5 py-1 rounded-lg bg-white/[0.06] border border-white/15 text-white placeholder-neutral-500 focus:outline-none focus:border-indigo-400 text-xs"
                />
              </div>

              <div className="flex items-center justify-end space-x-2 pt-1">
                <button
                  type="button"
                  onClick={() => setIsAddFormOpen(false)}
                  className="px-2.5 py-1 rounded-md text-neutral-400 hover:text-white text-[11px]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingEvent}
                  className="px-3 py-1 rounded-md bg-indigo-500 hover:bg-indigo-600 text-white font-medium text-[11px] shadow transition-all disabled:opacity-50"
                >
                  {isSubmittingEvent ? 'Saving...' : 'Create Event'}
                </button>
              </div>
            </form>
          )}

          {formFeedback && (
            <div className="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-xs flex items-center space-x-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>{formFeedback}</span>
            </div>
          )}

          {/* Monthly Day Grid */}
          <div className="p-3.5 rounded-xl bg-black/40 border border-white/[0.08] space-y-2">
            <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-mono font-semibold text-neutral-400">
              <span>Su</span><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span>
            </div>

            <div className="grid grid-cols-7 gap-1 text-center text-xs font-mono">
              {calendarCells.map((d, i) => {
                if (d === null) return <span key={i} className="py-1 opacity-0" />;
                const isToday =
                  d === now.getDate() &&
                  viewMonth === now.getMonth() &&
                  viewYear === now.getFullYear();
                const isSelected = selectedDayNumber === d;
                const dayEvents = eventsByDay[d] || [];
                const dayTasks = tasksByDay[d] || [];
                const hasEvents = dayEvents.length > 0;
                const hasTasks = dayTasks.length > 0;

                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      if (selectedDayNumber === d) {
                        setSelectedDayNumber(null);
                      } else {
                        setSelectedDayNumber(d);
                      }
                    }}
                    className={`relative py-1.5 rounded-lg flex flex-col items-center justify-center transition-all ${
                      isSelected
                        ? 'bg-indigo-500/40 text-white font-bold border border-indigo-400/80 shadow-[0_0_12px_rgba(99,102,241,0.5)]'
                        : isToday
                        ? 'bg-blue-500 text-white font-bold shadow-[0_0_10px_rgba(59,130,246,0.7)]'
                        : (hasEvents || hasTasks)
                        ? 'bg-white/[0.07] text-white hover:bg-white/[0.14] border border-white/10'
                        : 'text-neutral-300 hover:bg-white/10'
                    }`}
                  >
                    <span>{d}</span>
                    {(hasEvents || hasTasks) && (
                      <div className="flex items-center space-x-0.5 mt-0.5">
                        {hasEvents && (
                          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#38bdf8]" />
                        )}
                        {hasTasks && (
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shadow-[0_0_6px_#fbbf24]" />
                        )}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Agenda & Upcoming Events / Scheduled Tasks List */}
          <div className="p-3.5 rounded-xl bg-black/40 border border-white/[0.08] space-y-2.5">
            {(() => {
              const isSelectedToday =
                selectedDayNumber === now.getDate() &&
                viewMonth === now.getMonth() &&
                viewYear === now.getFullYear();
              const isSelectedTomorrow =
                selectedDayNumber === now.getDate() + 1 &&
                viewMonth === now.getMonth() &&
                viewYear === now.getFullYear();

              const totalEvents = displayedEvents.length;
              const totalTasks = displayedTasks.length;
              const totalCount = totalEvents + totalTasks;

              const showEvents = agendaFilter === 'all' || agendaFilter === 'calendar';
              const showTasks = agendaFilter === 'all' || agendaFilter === 'tasks';
              const visibleEventsCount = showEvents ? displayedEvents.length : 0;
              const visibleTasksCount = showTasks ? displayedTasks.length : 0;
              const hasItems = (visibleEventsCount + visibleTasksCount) > 0;

              return (
                <>
                  <div className="flex items-center justify-between text-xs pb-1.5 border-b border-white/[0.06] flex-wrap gap-2">
                    <div className="flex items-center space-x-1.5 font-medium text-white">
                      <CalendarCheck className="w-3.5 h-3.5 text-indigo-400" />
                      <span>
                        {isSelectedToday
                          ? `Today's Schedule (${viewMonthLong} ${selectedDayNumber})`
                          : isSelectedTomorrow
                          ? `Tomorrow's Schedule (${viewMonthLong} ${selectedDayNumber})`
                          : selectedDayNumber !== null
                          ? `Schedule for ${viewMonthLong} ${selectedDayNumber}`
                          : 'Upcoming Schedule'}
                      </span>
                      <span className="px-1.5 py-0.2 rounded-full bg-white/10 text-[10px] font-mono text-neutral-300">
                        {totalCount}
                      </span>
                    </div>

                    <div className="flex items-center space-x-1.5">
                      {/* Filter pills */}
                      <div className="flex items-center p-0.5 rounded-md bg-white/[0.05] border border-white/10 text-[10px]">
                        <button
                          type="button"
                          onClick={() => setAgendaFilter('all')}
                          className={`px-1.5 py-0.5 rounded transition-all ${
                            agendaFilter === 'all'
                              ? 'bg-white/20 text-white font-semibold'
                              : 'text-neutral-400 hover:text-white'
                          }`}
                        >
                          All ({totalCount})
                        </button>
                        <button
                          type="button"
                          onClick={() => setAgendaFilter('calendar')}
                          className={`px-1.5 py-0.5 rounded transition-all ${
                            agendaFilter === 'calendar'
                              ? 'bg-indigo-500/30 text-indigo-200 font-semibold border border-indigo-500/40'
                              : 'text-neutral-400 hover:text-white'
                          }`}
                        >
                          Calendar ({totalEvents})
                        </button>
                        <button
                          type="button"
                          onClick={() => setAgendaFilter('tasks')}
                          className={`px-1.5 py-0.5 rounded transition-all ${
                            agendaFilter === 'tasks'
                              ? 'bg-amber-500/30 text-amber-200 font-semibold border border-amber-500/40'
                              : 'text-neutral-400 hover:text-white'
                          }`}
                        >
                          Tasks ({totalTasks})
                        </button>
                      </div>

                      {selectedDayNumber !== null && (
                        <button
                          type="button"
                          onClick={() => setSelectedDayNumber(null)}
                          className="text-[10px] text-indigo-400 hover:text-indigo-300 font-medium px-2 py-0.5 rounded bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 transition-all"
                        >
                          Show All
                        </button>
                      )}
                    </div>
                  </div>

                  {hasItems ? (
                    <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                      {/* Render Calendar Events */}
                      {showEvents &&
                        displayedEvents.map((ev) => (
                          <div
                            key={ev.id}
                            className="p-2.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.08] flex items-start justify-between gap-2 transition-all group"
                          >
                            <div className="min-w-0 flex-1 space-y-1">
                              <div className="flex items-center space-x-1.5 flex-wrap">
                                <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-[10px] font-medium font-mono flex items-center gap-1">
                                  <CalendarIcon className="w-2.5 h-2.5" />
                                  <span>{formatEventTime(ev)}</span>
                                </span>
                                {ev.attendees && ev.attendees.length > 0 && (
                                  <span className="flex items-center space-x-1 text-[10px] text-neutral-400 font-mono">
                                    <Users className="w-2.5 h-2.5" />
                                    <span>{ev.attendees.length}</span>
                                  </span>
                                )}
                              </div>
                              <h4 className="text-xs font-semibold text-white tracking-tight truncate" title={ev.summary}>
                                {ev.summary || 'Untitled Event'}
                              </h4>
                              {ev.description && (
                                <p className="text-[11px] text-neutral-400 line-clamp-1">
                                  {ev.description}
                                </p>
                              )}
                            </div>

                            <div className="flex items-center space-x-1 shrink-0 pt-0.5">
                              {ev.htmlLink && (
                                <a
                                  href={ev.htmlLink}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="p-1 rounded-md text-neutral-400 hover:text-white hover:bg-white/10 transition-all"
                                  title="Open in Google Calendar"
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                </a>
                              )}
                              <button
                                type="button"
                                onClick={() => handleDeleteEvent(ev.id, ev.summary || 'event')}
                                className="p-1 rounded-md text-neutral-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
                                title="Delete event"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>
                        ))}

                      {/* Render Scheduled Tasks */}
                      {showTasks &&
                        displayedTasks.map((task) => (
                          <div
                            key={task.id}
                            className="p-2.5 rounded-lg bg-amber-500/[0.04] hover:bg-amber-500/[0.08] border border-amber-500/20 flex items-start justify-between gap-2 transition-all"
                          >
                            <div className="min-w-0 flex-1 space-y-1">
                              <div className="flex items-center space-x-1.5 flex-wrap">
                                <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] font-medium font-mono flex items-center gap-1">
                                  {task.task_type === 'reminder' ? (
                                    <Bell className="w-2.5 h-2.5" />
                                  ) : (
                                    <Zap className="w-2.5 h-2.5" />
                                  )}
                                  <span>{task.task_type === 'reminder' ? 'Reminder' : 'Task'}</span>
                                </span>
                                {task.schedule_definition?.frequency && (
                                  <span className="px-1.5 py-0.5 rounded bg-white/10 text-neutral-300 text-[10px] font-mono capitalize">
                                    {task.schedule_definition.frequency}
                                  </span>
                                )}
                                <span className="text-[10px] text-neutral-400 font-mono">
                                  {formatTaskTime(task)}
                                </span>
                              </div>
                              <h4 className="text-xs font-semibold text-white tracking-tight truncate" title={task.name}>
                                {task.name}
                              </h4>
                              {task.prompt && (
                                <p className="text-[11px] text-neutral-400 line-clamp-1">
                                  {task.prompt}
                                </p>
                              )}
                            </div>
                          </div>
                        ))}
                    </div>
                  ) : (
                    <div className="py-4 text-center text-neutral-400 text-xs space-y-1">
                      <p>
                        {isSelectedToday
                          ? 'No calendar events or scheduled tasks for today.'
                          : selectedDayNumber !== null
                          ? `No events or tasks scheduled for ${viewMonthLong} ${selectedDayNumber}.`
                          : 'No upcoming events or scheduled tasks found.'}
                      </p>
                      <button
                        type="button"
                        onClick={() => setIsAddFormOpen(true)}
                        className="text-indigo-400 hover:text-indigo-300 text-[11px] font-medium inline-flex items-center gap-1"
                      >
                        <Plus className="w-3 h-3" />
                        <span>Schedule an event</span>
                      </button>
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
};
