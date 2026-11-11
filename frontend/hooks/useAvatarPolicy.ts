import { useEffect, useState } from 'react';
import api from '../services/mockApi';

const fallback = { maxBytes: 5 * 1024 * 1024, contentTypes: ['image/jpeg', 'image/png', 'image/webp'] };
let policyRequest: ReturnType<typeof api.getAvatarPolicy> | undefined;
function loadPolicy() {
  if (!policyRequest) policyRequest = api.getAvatarPolicy().then(value => {
    if (!(value?.maxBytes > 0) || !Array.isArray(value.contentTypes)) throw new Error('Invalid avatar policy');
    return value;
  }).catch(error => { policyRequest = undefined; throw error; });
  return policyRequest;
}

export function useAvatarPolicy() {
  const [policy, setPolicy] = useState(fallback);
  useEffect(() => {
    let active = true;
    loadPolicy().then(value => { if (active) setPolicy(value); }).catch(() => {});
    return () => { active = false; };
  }, []);
  return policy;
}
