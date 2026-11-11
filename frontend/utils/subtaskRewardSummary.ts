import type { Task } from '../types';

/** Ledger-earned and incomplete base availability are intentionally separate. */
export function summarizeSubtaskRewards(tasks:Task[], recipient?:string) {
  return tasks.reduce((total, task) => {
    const reward = task.subtaskRewards;
    if (reward) {
      total.earned += recipient ? reward.earned_by_recipient[recipient] ?? 0 : reward.earned;
      total.availableBase += !recipient || reward.available_recipient_id === recipient ? reward.available_base : 0;
    }
    return total;
  }, { earned:0, availableBase:0 });
}
