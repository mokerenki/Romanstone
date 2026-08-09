"use client";

import { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { 
  Bot, 
  Puzzle,
  Calendar, 
  Library, 
  Settings,
  ChevronLeft,
  ChevronRight,
  Home,
  Clock,
  BarChart3,
  Sparkles
} from 'lucide-react';
import Link from 'next/link';

interface NavItem {
  icon: React.ReactNode;
  label: string;
  href: string;
  badge?: string;
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) {
        setCollapsed(true);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  
  const navItems: NavItem[] = [
    { icon: <Home className="w-5 h-5" />, label: 'Dashboard', href: '/' },
    { icon: <Bot className="w-5 h-5" />, label: 'Agent', href: '/agent', badge: 'New' },
    { icon: <Puzzle className="w-5 h-5" />, label: 'Integrations', href: '/integrations', badge: '3' },
    { icon: <Calendar className="w-5 h-5" />, label: 'Scheduled', href: '/scheduled' },
    { icon: <Library className="w-5 h-5" />, label: 'Library', href: '/library' },
    { icon: <Clock className="w-5 h-5" />, label: 'History', href: '/history' },
    { icon: <BarChart3 className="w-5 h-5" />, label: 'Cost', href: '/cost' },
    { icon: <Settings className="w-5 h-5" />, label: 'Settings', href: '/settings' },
  ];

  // Safe active route detection
  const isActive = (href: string) => {
    if (href === '/') {
      return pathname === '/';
    }
    // Exact match OR starts with href/ (so /agent matches /agent/chat, but not /agents)
    return pathname === href || pathname?.startsWith(`${href}/`);
  };

  if (!mounted) {
    return null;
  }

  return (
    <aside className={`bg-synthai-surface/95 border-r border-synthai-border transition-all duration-300 ${
      collapsed ? 'w-16' : 'w-64'
    } h-screen sticky top-0 flex flex-col backdrop-blur-sm`}>
      <div className="flex items-center justify-between p-4 border-b border-synthai-border">
        {!collapsed && (
          <Link href="/" className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-brand-400" />
            <span className="text-xl font-bold text-gradient">
              synthAI
            </span>
          </Link>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1 rounded-lg hover:bg-synthai-surface-hover text-text-secondary transition-colors"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>
      
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                active 
                  ? 'bg-brand-500/20 text-brand-400 border border-brand-500/20' 
                  : 'text-text-secondary hover:bg-synthai-surface-hover hover:text-text-primary'
              }`}
            >
              {item.icon}
              {!collapsed && (
                <>
                  <span className="text-sm font-medium">{item.label}</span>
                  {item.badge && (
                    <span className="ml-auto text-xs px-2 py-0.5 bg-brand-500/20 text-brand-400 rounded-full">
                      {item.badge}
                    </span>
                  )}
                </>
              )}
            </Link>
          );
        })}
      </nav>
      
      <div className="p-4 border-t border-synthai-border">
        <div className={`flex items-center gap-3 ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-8 h-8 rounded-full bg-brand-gradient flex items-center justify-center text-white font-semibold text-sm">
            VL
          </div>
          {!collapsed && (
            <div className="flex-1">
              <p className="text-sm font-medium text-text-primary">Victor Lefoka</p>
              <p className="text-xs text-text-muted">Free Plan</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}