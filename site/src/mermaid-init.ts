import mermaid from 'mermaid';

export function initMermaid(): void {
  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    themeVariables: {
      primaryColor: '#1c2540',
      primaryTextColor: '#f0f2ff',
      primaryBorderColor: '#7c5cfc',
      lineColor: '#7c5cfc',
      secondaryColor: '#161d35',
      tertiaryColor: '#0f1526',
      fontFamily: 'Inter, sans-serif',
      fontSize: '13px',
    },
  });

  void mermaid.run({ querySelector: '.mermaid' });
}
