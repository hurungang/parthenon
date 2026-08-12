import { initAnimations } from './animations';
import { initMermaid } from './mermaid-init';
import { initTabs } from './tabs';

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initAnimations();
  initMermaid();
});
