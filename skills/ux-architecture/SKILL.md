---
name: ux-architecture
description: Technical architecture and UX specialist providing developers with CSS systems, layout frameworks, and clear implementation guidance. Adapted from msitarzewski/agency-agents.
---

## Triggers

- ux architecture
- css architecture
- design system css
- layout framework
- responsive framework
- css variables
- design tokens css
- theme toggle
- dark mode toggle
- information architecture
- developer handoff
- css foundation
- grid layout
- flexbox layout
- breakpoint strategy
- mobile first
- component architecture
- technical foundation

## Instructions

### CSS Design System Foundation
Create developer-ready CSS foundations with:

1. **CSS Custom Properties**: Light/dark theme color tokens, typography scale, spacing system, container widths
2. **Theme System**: Light theme defaults, `[data-theme="dark"]` overrides, `prefers-color-scheme` media query fallback
3. **Typography Scale**: Semantic heading classes (.text-heading-1 through .text-heading-6) with font-size, font-weight, line-height, margin
4. **Spacing System**: 4px-based scale (space-1 through space-16) for consistent vertical rhythm
5. **Container System**: Full-width mobile with responsive max-widths (640px, 768px, 1024px, 1280px)

### Layout Framework
Design layout patterns using modern CSS:
- **Grid Patterns**: 2-column, 3-column, 4-column with responsive single-column fallback
- **Flexbox Utilities**: Alignment, distribution, wrapping helpers
- **Hero Section**: Full viewport height, centered content pattern
- **Sidebar Layout**: 2fr main + 1fr sidebar with gap
- **Card Layout**: CSS Grid auto-fit with minimum card widths

### Theme Toggle System
Always include a light/dark/system theme toggle:
- HTML component with `role="radiogroup"` and `aria-label`
- JavaScript ThemeManager class handling localStorage persistence and system preference detection
- CSS for toggle appearance with active state indication

### Information Architecture
- **Page Hierarchy**: 5-7 main navigation sections maximum
- **Visual Weight System**: H1 > H2 > H3 > Body > CTAs with decreasing visual prominence
- **Content Flow**: Logical progression through sections
- **CTA Placement**: Above fold, section ends, footer

### Interaction Patterns
- Smooth scroll to sections with active state indicators
- Theme switching with instant visual feedback
- Forms with clear labels, validation feedback, progress indicators
- Buttons with hover, focus, and loading states
- Cards with subtle hover effects and clear clickable areas

### Developer Handoff
- Generate CSS foundation files with documented patterns
- Specify component requirements and dependencies
- Include responsive behavior specifications
- Establish implementation priority order:
  1. Design system variables
  2. Layout structure
  3. Component base
  4. Content integration
  5. Interactive polish

### EloPhanto Tool Integration
- Use `browser_navigate` to review existing site implementations
- Use `knowledge_write` to persist architecture decisions and CSS systems
- Use `web_search` to research CSS patterns and browser compatibility

## Deliverables

### CSS Design System
```css
:root {
  --bg-primary: [spec-light-bg];
  --bg-secondary: [spec-light-secondary];
  --text-primary: [spec-light-text];
  --text-secondary: [spec-light-text-muted];
  --border-color: [spec-light-border];
  --primary-color: [spec-primary];
  --secondary-color: [spec-secondary];
  --accent-color: [spec-accent];

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.25rem;
  --text-2xl: 1.5rem;
  --text-3xl: 1.875rem;

  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --space-16: 4rem;

  --container-sm: 640px;
  --container-md: 768px;
  --container-lg: 1024px;
  --container-xl: 1280px;
}

[data-theme="dark"] {
  --bg-primary: [spec-dark-bg];
  --text-primary: [spec-dark-text];
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg-primary: [spec-dark-bg];
    --text-primary: [spec-dark-text];
  }
}
```

### Theme Toggle HTML
```html
<div class="theme-toggle" role="radiogroup" aria-label="Theme selection">
  <button class="theme-toggle-option" data-theme="light" role="radio" aria-checked="false">Light</button>
  <button class="theme-toggle-option" data-theme="dark" role="radio" aria-checked="false">Dark</button>
  <button class="theme-toggle-option" data-theme="system" role="radio" aria-checked="true">System</button>
</div>
```

### ThemeManager JavaScript
```javascript
class ThemeManager {
  constructor() {
    this.currentTheme = this.getStoredTheme() || this.getSystemTheme();
    this.applyTheme(this.currentTheme);
    this.initializeToggle();
  }

  getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  getStoredTheme() { return localStorage.getItem('theme'); }

  applyTheme(theme) {
    if (theme === 'system') {
      document.documentElement.removeAttribute('data-theme');
      localStorage.removeItem('theme');
    } else {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('theme', theme);
    }
    this.currentTheme = theme;
    this.updateToggleUI();
  }

  initializeToggle() {
    const toggle = document.querySelector('.theme-toggle');
    if (toggle) {
      toggle.addEventListener('click', (e) => {
        if (e.target.matches('.theme-toggle-option')) {
          this.applyTheme(e.target.dataset.theme);
        }
      });
    }
  }

  updateToggleUI() {
    document.querySelectorAll('.theme-toggle-option').forEach(option => {
      option.classList.toggle('active', option.dataset.theme === this.currentTheme);
    });
  }
}

document.addEventListener('DOMContentLoaded', () => new ThemeManager());
```

### Architecture Deliverable Template
```markdown
# [Project Name] Technical Architecture & UX Foundation

## CSS Architecture
- **Design System Variables**: Color, typography, spacing tokens
- **Layout Framework**: Container, grid, flexbox patterns
- **Theme System**: Light/dark/system with toggle component

## UX Structure
- **Information Architecture**: Page hierarchy, navigation, content flow
- **Responsive Strategy**: Mobile-first with breakpoints at 640/768/1024/1280px
- **Accessibility Foundation**: Keyboard nav, screen readers, WCAG AA contrast

## Developer Implementation Guide
1. Foundation Setup: Design system variables
2. Layout Structure: Responsive containers and grids
3. Component Base: Reusable component templates
4. Content Integration: Proper hierarchy
5. Interactive Polish: Hover states and animations

## File Structure
css/design-system.css, css/layout.css, css/components.css, css/utilities.css
js/theme-manager.js, js/main.js
```

## Success Metrics

- Developers can implement designs without architectural decisions
- CSS remains maintainable and conflict-free throughout development
- UX patterns guide users naturally through content and conversions
- Projects have consistent, professional appearance baseline
- Technical foundation supports both current needs and future growth

## Verify

- The change was rendered in a browser/simulator and a screenshot or DOM snapshot was captured, not just code-reviewed
- Layout was checked at the breakpoints the ux-architecture guide calls out (mobile + desktop minimum); evidence of each is attached
- Color, typography, and spacing values used come from the project's design tokens / theme, not hard-coded ad-hoc values
- Keyboard navigation and focus order were exercised on every interactive element introduced
- Reduced-motion / dark-mode (when supported) variants were verified, not assumed to inherit
- No console errors or hydration warnings were emitted during the verification render
