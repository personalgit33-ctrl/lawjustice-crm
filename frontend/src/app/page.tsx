'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { tokens } from '@/lib/api';
export default function Home() {
  const r = useRouter();
  useEffect(() => { r.replace(tokens.access ? '/dashboard' : '/login'); }, [r]);
  return null;
}
