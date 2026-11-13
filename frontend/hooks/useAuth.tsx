import React, { createContext, useState, useContext, useEffect, useRef } from 'react';
import { User, Role } from '../types';
import api from '../services/mockApi';
import { getAccessToken } from '../services/tokenStorage';
import { sessionIdentity } from '../services/sessionRefresh';
import { AUTH_EXPIRED_EVENT, USER_PROFILE_UPDATED_EVENT } from '../utils/appEvents';
import PageLoader from '../components/loading/PageLoader';

// Auth Context
interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, pass: string) => Promise<void>;
  logout: () => void;
  updateUserInContext: (user: User) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);

  useEffect(() => {
    let mounted = true;
    let observed = sessionIdentity(getAccessToken());
    const checkLoggedIn = async () => {
      const request = ++generation.current;
      const expected = sessionIdentity(getAccessToken());
      observed = expected;
      const current = () => mounted && request === generation.current
        && sessionIdentity(getAccessToken()) === expected;
      setLoading(true);
      try {
        if (!getAccessToken()) {
          if (current()) setUser(null);
          return;
        }
        const currentUser = await api.getCurrentUser();
        if (current()) setUser(currentUser);
      } catch {
        if (current()) setUser(null);
      } finally {
        if (current()) setLoading(false);
      }
    };
    const handleAuthExpired = () => {
      ++generation.current;
      observed = sessionIdentity(getAccessToken());
      setUser(null);
      setLoading(false);
      // ProtectedRoute owns the login redirect; do not compete with it here.
    };
    const changed = (event: StorageEvent) => {
      if (event.key !== null && event.key !== 'vee_access_token' && event.key !== 'vee_refresh_token') return;
      if (sessionIdentity(getAccessToken()) !== observed) void checkLoggedIn();
    };
    void checkLoggedIn();
    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    window.addEventListener('storage', changed);
    return () => {
      mounted = false; ++generation.current;
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
      window.removeEventListener('storage', changed);
    };
  }, []);
  
  useEffect(() => {
    const updated = (event: Event) => {
      const profile = (event as CustomEvent<User>).detail;
      setUser(previous => previous?.id === profile.id ? profile : previous);
    };
    window.addEventListener(USER_PROFILE_UPDATED_EVENT, updated);
    return () => window.removeEventListener(USER_PROFILE_UPDATED_EVENT, updated);
  }, []);

  const login = async (email: string, pass: string) => {
    const request = ++generation.current;
    const loggedInUser = await api.login(email, pass);
    if (request === generation.current) { setUser(loggedInUser); setLoading(false); }
  };

  const logout = () => {
    ++generation.current;
    api.logout();
    setUser(null);
    setLoading(false);
  };

  const updateUserInContext = (updatedUser: User) => {
    setUser(updatedUser);
  };

  const value = { user, loading, login, logout, updateUserInContext };

  return (
    <AuthContext.Provider value={value}>
      {loading ? (
        <PageLoader />
      ) : (
        children
      )}
    </AuthContext.Provider>
  );
};

export const useOptionalAuth = () => useContext(AuthContext);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};


// Search Context
interface SearchContextType {
    searchQuery: string;
    setSearchQuery: (query: string) => void;
    debouncedSearchQuery: string;
}

const SearchContext = createContext<SearchContextType | undefined>(undefined);

export const SearchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [searchQuery, setSearchQuery] = useState('');
    const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');

    useEffect(() => {
        const handler = setTimeout(() => {
            setDebouncedSearchQuery(searchQuery);
        }, 300); // 300ms debounce delay

        return () => {
            clearTimeout(handler);
        };
    }, [searchQuery]);

    return (
        <SearchContext.Provider value={{ searchQuery, setSearchQuery, debouncedSearchQuery }}>
            {children}
        </SearchContext.Provider>
    );
};

export const useSearch = () => {
    const context = useContext(SearchContext);
    if (context === undefined) {
        throw new Error('useSearch must be used within a SearchProvider');
    }
    return context;
};

// Theme Context
type Theme = 'light' | 'dark' | 'colorful' | 'system';

interface ThemeContextType {
    theme: Theme;
    setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [theme, setThemeState] = useState<Theme>(() => {
        const storedTheme = localStorage.getItem('zenith-task-theme') as Theme | null;
        return storedTheme || 'dark';
    });

    const setTheme = (newTheme: Theme) => {
        setThemeState(newTheme);
        localStorage.setItem('zenith-task-theme', newTheme);
    };

    useEffect(() => {
        const root = window.document.documentElement;
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        const applyTheme = () => {
            const prefersDark = mediaQuery.matches;
            const resolvedTheme = theme === 'system' ? (prefersDark ? 'dark' : 'light') : theme;
            const useColorful = resolvedTheme === 'colorful';
            const useDark = resolvedTheme === 'dark';

            if (useColorful) {
                root.classList.add('theme-colorful');
                root.classList.remove('dark', 'theme-light');
            } else {
                root.classList.remove('theme-colorful');
                root.classList.toggle('dark', useDark);
                if (!useDark) {
                    root.classList.remove('dark');
                    root.classList.add('theme-light');
                } else {
                    root.classList.remove('theme-light');
                }
            }
        };

        applyTheme();

        const handleChange = () => {
            if (theme === 'system') {
                applyTheme();
            }
        };

        mediaQuery.addEventListener('change', handleChange);
        return () => mediaQuery.removeEventListener('change', handleChange);

    }, [theme]);

    return (
        <ThemeContext.Provider value={{ theme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    );
}

export const useTheme = () => {
    const context = useContext(ThemeContext);
    if (!context) {
        console.warn('useTheme used without ThemeProvider; falling back to dark theme.');
        return {
            theme: 'dark' as Theme,
            setTheme: () => {},
        };
    }
    return context;
};


