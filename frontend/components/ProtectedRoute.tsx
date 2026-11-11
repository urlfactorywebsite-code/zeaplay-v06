
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { Role } from '../types';
import { NavigationAccess } from '../hooks/useNavigation';

interface ProtectedRouteProps {
  children: React.ReactElement;
  roles: Role[];
  validateNavigation?: boolean;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, roles, validateNavigation = true }) => {
  const { user } = useAuth();
  const location = useLocation();

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (!roles.includes(user.role)) {
    return <Navigate to="/settings/profile" replace state={{ navigationDenial: 'Your role does not have access to this page.' }} />;
  }

  return validateNavigation ? <NavigationAccess>{children}</NavigationAccess> : children;
};

export default ProtectedRoute;
