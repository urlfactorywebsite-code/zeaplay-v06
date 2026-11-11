import React from 'react';
import { User } from '../types';
import Avatar from './Avatar';

export default function EmployeeIdentityCard({ user, department }: { user: User; department?: string }) {
  return <section aria-label="Employee digital ID card" className="mt-5 overflow-hidden rounded-2xl border border-cyan-400/30 bg-slate-950 p-5 text-slate-100 transition-colors hover:border-cyan-400/60 sm:p-6">
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
      <p className="text-xs font-semibold tracking-[0.18em] text-cyan-300">ZEA.PLAY · EMPLOYEE ID</p>
      <span className="rounded-full border border-white/15 px-2.5 py-1 text-xs">{user.status}</span>
    </div>
    <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
      <Avatar user={user} size={112} className="h-28 w-28 text-3xl" />
      <div className="min-w-0 flex-1 space-y-3">
        <div><h3 className="break-words text-2xl font-semibold">{user.name}</h3>
          <p className="mt-1 break-words text-sm text-slate-300">{user.title || 'Designation not set'}</p></div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1">Role: {user.role}</span>
          <span className="rounded-full border border-white/15 px-3 py-1">{department || user.department || 'Department not set'}</span>
        </div>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-xs text-slate-400">Employee ID</dt><dd className="break-words">{user.employerId || 'Not assigned'}</dd></div>
          <div><dt className="text-xs text-slate-400">Email</dt><dd className="break-all">{user.email}</dd></div>
        </dl>
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">{user.profileBio || 'No professional bio added yet.'}</p>
      </div>
    </div>
    <div className="mt-5 border-t border-white/10 pt-4"><h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Skills and expertise</h4>
      {user.skills?.length ? <ul className="flex flex-wrap gap-2">{user.skills.map(skill => <li key={skill.toLowerCase()} className="max-w-full break-words rounded-full border border-cyan-400/25 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-100">{skill}</li>)}</ul> : <p className="text-sm text-slate-400">No skills added.</p>}
    </div>
  </section>;
}
