export function initTabs(): void {
  const pills = document.querySelectorAll<HTMLButtonElement>('.tab-pill');
  const panels = document.querySelectorAll<HTMLElement>('.tab-panel');

  pills.forEach((pill) => {
    pill.addEventListener('click', () => {
      pills.forEach((item) => item.classList.remove('active'));
      panels.forEach((panel) => panel.classList.remove('active'));

      pill.classList.add('active');

      const targetId = pill.dataset.tab;
      if (!targetId) {
        return;
      }

      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add('active');
      }
    });
  });
}
