import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

// Legacy bookmarks retain filters, anchors and navigation state without adding
// an extra history entry or changing backend endpoint paths.
const PreserveLocationRedirect: React.FC<{ to: string }> = ({ to }) => {
  const { search, hash, state } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} state={state} replace />;
};

export default PreserveLocationRedirect;
