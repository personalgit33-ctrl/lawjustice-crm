'use client';
import { useEffect, useRef } from 'react';
import { API_URL, tokens } from './api';
import type { WsEvent } from './types';

type Handler = (e: WsEvent) => void;
const handlers = new Set<Handler>();
let sock: WebSocket | null = null;
let timer: any = null;
let attempt = 0;
let started = false;

function wsUrl() {
  const base = API_URL.replace(/^http/, 'ws');
  return `${base}/ws/events/?token=${encodeURIComponent(tokens.access || '')}`;
}
function connect() {
  if (typeof window === 'undefined' || !tokens.access) return;
  try { sock = new WebSocket(wsUrl()); } catch { schedule(); return; }
  sock.onopen = () => { attempt = 0; };
  sock.onmessage = (m) => { try { const e = JSON.parse(m.data) as WsEvent; handlers.forEach((h) => { try { h(e); } catch {} }); } catch {} };
  sock.onclose = () => { sock = null; schedule(); };
  sock.onerror = () => { try { sock?.close(); } catch {} };
}
function schedule() {
  if (!started) return;
  clearTimeout(timer);
  attempt = Math.min(attempt + 1, 6);
  timer = setTimeout(connect, 1000 * 2 ** (attempt - 1));
}
export function startEvents() { if (started) return; started = true; connect(); }
export function stopEvents() { started = false; clearTimeout(timer); try { sock?.close(); } catch {} sock = null; }

/** Подписка на события реального времени. */
export function useEvents(fn: Handler, deps: any[] = []) {
  const ref = useRef(fn); ref.current = fn;
  useEffect(() => {
    const h: Handler = (e) => ref.current(e);
    handlers.add(h);
    return () => { handlers.delete(h); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
