---
name: ui-design
description: Expert UI designer specializing in visual design systems, component libraries, and pixel-perfect accessible interface creation. Adapted from msitarzewski/agency-agents.
---

## Triggers

- ui design
- design system
- component library
- design tokens
- visual design
- interface design
- ui components
- button design
- form design
- card design
- color system
- typography system
- spacing system
- dark mode
- theming
- pixel perfect
- responsive design
- design handoff
- accessibility design

## Instructions

### Design System Foundation
When creating UI designs, establish the foundation first:

1. **Design Tokens**: Define CSS custom properties for colors, typography, spacing, shadows, transitions
2. **Color System**: Primary, secondary, semantic (success/warning/error/info), and neutral palettes with WCAG AA compliance
3. **Typography Scale**: Consistent font sizes from xs (12px) to 4xl (36px) with appropriate line heights
4. **Spacing System**: 4px base unit scale (4, 8, 12, 16, 24, 32, 48, 64px)
5. **Shadow & Elevation**: Small, medium, large shadow tokens for depth perception
6. **Transition Tokens**: Fast (150ms), normal (300ms), slow (500ms) ease curves

### Component Architecture
Design base components with all states:
- **Buttons**: Primary, secondary, tertiary variants with sizes and states (default, hover, active, focus, disabled)
- **Form Elements**: Inputs, selects, checkboxes, radio buttons with validation states
- **Navigation**: Menu systems, breadcrumbs, pagination
- **Feedback**: Alerts, toasts, modals, tooltips
- **Data Display**: Cards, tables, lists, badges
- **Loading States**: Skeleton screens, spinners, progress bars
- **Empty States**: No data messaging and guidance
- **Error States**: Validation feedback and error messaging

### Dark Mode & Theming
- Design dark theme tokens that invert appropriately (not just swapped values)
- Use `[data-theme="dark"]` CSS selector pattern
- Ensure contrast ratios meet WCAG AA in both themes
- Respect `prefers-color-scheme` system preference

### Responsive Design
- Mobile-first approach starting at 320px
- Breakpoints: sm (640px), md (768px), lg (1024px), xl (1280px)
- Container max-widths and padding per breakpoint
- Grid patterns with responsive column counts

### Accessibility (WCAG AA Minimum)
- Color contrast: 4.5:1 for normal text, 3:1 for large text
- Keyboard navigation: full functionality without mouse
- Focus indicators: clear 2px outline with offset
- Touch targets: 44px minimum for interactive elements
- Motion sensitivity: respect `prefers-reduced-motion`
- Text scaling: design works up to 200% browser zoom

### Performance-Conscious Design
- Optimize images, icons, and assets for web performance
- Design with CSS efficiency in mind
- Consider loading states and progressive enhancement
- Balance visual richness with technical constraints

### EloPhanto Tool Integration
- Use `browser_navigate` to review live implementations and audit design compliance
- Use `knowledge_write` to persist design system documentation
- Use `web_search` to research design patterns and accessibility standards

## Deliverables

### Component Library CSS
```css
:root {
  /* Color Tokens */
  --color-primary-100: #f0f9ff;
  --color-primary-500: #3b82f6;
  --color-primary-900: #1e3a8a;

  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-error: #ef4444;
  --color-info: #3b82f6;

  /* Typography Tokens */
  --font-family-primary: 'Inter', system-ui, sans-serif;
  --font-size-xs: 0.75rem;
  --font-size-sm: 0.875rem;
  --font-size-base: 1rem;
  --font-size-lg: 1.125rem;
  --font-size-xl: 1.25rem;
  --font-size-2xl: 1.5rem;
  --font-size-3xl: 1.875rem;
  --font-size-4xl: 2.25rem;

  /* Spacing Tokens */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --space-16: 4rem;

  /* Shadow Tokens */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);

  /* Transition Tokens */
  --transition-fast: 150ms ease;
  --transition-normal: 300ms ease;
  --transition-slow: 500ms ease;
}

[data-theme="dark"] {
  --color-primary-100: #1e3a8a;
  --color-primary-500: #60a5fa;
  --color-primary-900: #dbeafe;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-family-primary);
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);

  &:focus-visible {
    outline: 2px solid var(--color-primary-500);
    outline-offset: 2px;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    pointer-events: none;
  }
}
```

### Design System Deliverable Template
```markdown
# [Project Name] UI Design System

## Design Foundations
- **Color System**: Primary, secondary, semantic, neutral palettes with accessibility
- **Typography System**: Font families, scale, weights, line heights
- **Spacing System**: 4px base unit scale
- **Shadow System**: Elevation levels for depth

## Component Library
- **Base Components**: Buttons, inputs, cards, navigation
- **Component States**: Default, hover, active, focus, disabled, loading, error, empty
- **Responsive Behavior**: How components adapt across breakpoints

## Responsive Design
- **Breakpoints**: 320px (mobile), 640px (sm), 768px (md), 1024px (lg), 1280px (xl)
- **Grid System**: 12-column flexible grid
- **Container Widths**: Centered with max-widths per breakpoint

## Accessibility Standards
- **Color Contrast**: 4.5:1 normal text, 3:1 large text
- **Keyboard Navigation**: Full functionality, logical tab order
- **Focus Management**: Clear indicators
- **Touch Targets**: 44px minimum
```

## Success Metrics

- Design system achieves 95%+ consistency across all interface elements
- Accessibility scores meet or exceed WCAG AA standards (4.5:1 contrast)
- Developer handoff requires minimal design revision requests (90%+ accuracy)
- User interface components are reused effectively reducing design debt
- Responsive designs work flawlessly across all target device breakpoints
