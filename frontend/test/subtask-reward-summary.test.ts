import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeSubtaskRewards } from '../utils/subtaskRewardSummary';
import type { Task } from '../types';

test('earned ledger totals never include incomplete availability or duplicate ownership', () => {
  const tasks = [{ subtaskRewards:{ earned:45, available_base:30, base_capacity:60,
    eligible_count:3, earned_by_recipient:{ old:0, current:45 }, available_recipient_id:'current', policy_version:'subtask-additional-v1' } }, {}] as unknown as Task[];
  assert.deepEqual(summarizeSubtaskRewards(tasks), { earned:45, availableBase:30 });
  assert.deepEqual(summarizeSubtaskRewards(tasks,'current'), { earned:45, availableBase:30 });
  assert.deepEqual(summarizeSubtaskRewards(tasks,'old'), { earned:0, availableBase:0 });
});

test('compensating ledger net may be negative while availability stays separate', () => {
  const tasks = [{ subtaskRewards:{ earned:-15, available_base:60, base_capacity:60,
    eligible_count:3, earned_by_recipient:{ current:-15 }, available_recipient_id:'current', policy_version:'subtask-additional-v1' } }] as unknown as Task[];
  assert.deepEqual(summarizeSubtaskRewards(tasks,'current'), { earned:-15, availableBase:60 });
});
