// frontend/src/components/QuickActions.tsx

"use client";

import { 
  FileText, 
  Globe, 
  Code, 
  TrendingUp,
  Search,
  Presentation,
  Mail,
  Users,
  Building2,
  BarChart3,
  Shield
} from 'lucide-react';

interface QuickAction {
  icon: React.ReactNode;
  label: string;
  action: string;
}

interface QuickActionsProps {
  onAction: (action: string) => void;
  onMore?: () => void; // NEW: Optional callback for "More" button
}

export default function QuickActions({ onAction, onMore }: QuickActionsProps) {
  const actions: QuickAction[] = [
    { icon: <Presentation className="w-4 h-4" />, label: 'Create slides', action: 'create_slides' },
    { icon: <Globe className="w-4 h-4" />, label: 'Build website', action: 'build_website' },
    { icon: <Code className="w-4 h-4" />, label: 'Design', action: 'design' },
    { icon: <FileText className="w-4 h-4" />, label: 'Write document', action: 'document' },
    { icon: <Search className="w-4 h-4" />, label: 'Research', action: 'research' },
    { icon: <Mail className="w-4 h-4" />, label: 'Draft email', action: 'draft_email' },
    { icon: <Users className="w-4 h-4" />, label: 'Sales outreach', action: 'sales_outreach' },
    { icon: <BarChart3 className="w-4 h-4" />, label: 'Financial analysis', action: 'financial_analysis' },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((action, index) => (
        <button
          key={index}
          onClick={() => onAction(action.action)}
          className="flex items-center gap-2 px-4 py-2 bg-synthai-surface hover:bg-synthai-surface-hover rounded-lg text-sm text-text-secondary hover:text-text-primary transition-colors border border-synthai-border hover:border-brand-500/30"
        >
          <span className="text-brand-400">{action.icon}</span>
          <span>{action.label}</span>
        </button>
      ))}
      <button 
        onClick={onMore || (() => {})} // Safe fallback if no handler
        className="px-4 py-2 text-text-muted hover:text-text-secondary rounded-lg text-sm transition-colors hover:bg-synthai-surface-hover"
      >
        + More
      </button>
    </div>
  );
}