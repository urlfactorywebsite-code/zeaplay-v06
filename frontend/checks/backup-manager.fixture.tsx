import React from 'react';
import { createRoot } from 'react-dom/client';
import BackupManager from '../components/BackupManager';
import '../index.css';
const legacyEntry =
  new URLSearchParams(location.search).get('entry') === 'legacy';
createRoot(document.getElementById('root')!).render(
  <div className="bg-surface border border-border-color rounded-xl p-6">
    <BackupManager
      requestedBy="Workspace Owner"
      initialTab={legacyEntry ? 'import' : 'export'}
      initialDataset={legacyEntry ? 'users' : ''}
      initialFile={
        legacyEntry
          ? new File(['id,name\nowner,Owner\n'], 'users.csv', {
              type: 'text/csv',
            })
          : null
      }
    />
  </div>,
);
