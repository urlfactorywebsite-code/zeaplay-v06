import React, { useId, useState } from 'react';

export default function SkillsEditor({ value, onChange, suggestions = [] }: {
  value: string[]; onChange: (skills: string[]) => void; suggestions?: string[];
}) {
  const id = useId();
  const [input, setInput] = useState('');
  const add = () => {
    const skill = input.trim().replace(/\s+/g, ' ');
    if (!skill || skill.length > 60 || value.length >= 30) return;
    if (!value.some(item => item.toLocaleLowerCase() === skill.toLocaleLowerCase())) onChange([...value, skill]);
    setInput('');
  };
  return <div className="space-y-3">
    <label htmlFor={id} className="text-sm font-medium text-text-secondary">Skills and expertise</label>
    <div className="flex gap-2">
      <input id={id} list={`${id}-options`} value={input} maxLength={60} placeholder="Search or add a skill"
        onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
        className="min-w-0 flex-1 rounded-lg border border-border-color bg-background px-3 py-2 text-text-primary" />
      <datalist id={`${id}-options`}>{suggestions.filter(skill => !value.some(item => item.toLowerCase() === skill.toLowerCase())).map(skill => <option key={skill} value={skill} />)}</datalist>
      <button type="button" onClick={add} disabled={!input.trim() || value.length >= 30} className="rounded-lg border border-cyan-500/40 px-3 py-2 text-primary disabled:opacity-50">Add</button>
    </div>
    <ul className="flex flex-wrap gap-2" aria-label="Profile skills">{value.map(skill => <li key={skill.toLowerCase()} className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-sm">
      {skill}<button type="button" aria-label={`Remove ${skill}`} onClick={() => onChange(value.filter(item => item !== skill))} className="px-1">×</button>
    </li>)}</ul>
    <p className="text-xs text-text-secondary">Up to 30 skills, 60 characters each.</p>
  </div>;
}
