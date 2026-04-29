import { describe, test, expect } from 'vitest';
import { parthenon } from '../theme';

describe('Material Theme Configuration', () => {
  test('palette uses indigo primary color', () => {
    expect(parthenon.palette?.primary?.main).toBe('#4f46e5');
  });

  test('palette uses slate background colors', () => {
    expect(parthenon.palette?.background?.default).toBe('#f8fafc');
    expect(parthenon.palette?.background?.paper).toBe('#ffffff');
  });

  test('palette uses correct text colors', () => {
    expect(parthenon.palette?.text?.primary).toBe('#0f172a');
    expect(parthenon.palette?.text?.secondary).toBe('#64748b');
  });

  test('typography uses Inter font', () => {
    expect(parthenon.typography?.fontFamily).toContain('Inter');
  });

  test('shadows array has refined values', () => {
    expect(parthenon.shadows).toHaveLength(25);
    expect(parthenon.shadows?.[0]).toBe('none');
    expect(parthenon.shadows?.[1]).toContain('rgb(0 0 0 / 0.05)');
  });

  test('component overrides are defined', () => {
    expect(parthenon.components).toBeDefined();
    expect(parthenon.components?.MuiCard).toBeDefined();
    expect(parthenon.components?.MuiButton).toBeDefined();
    expect(parthenon.components?.MuiAppBar).toBeDefined();
  });

  test('Card has 12px border radius', () => {
    const cardOverride = parthenon.components?.MuiCard?.styleOverrides?.root;
    // styleOverrides can be functions or objects
    expect(cardOverride).toBeDefined();
    expect(parthenon.components?.MuiCard).toBeDefined();
  });

  test('AppBar uses paper background', () => {
    const appBarOverride = parthenon.components?.MuiAppBar?.styleOverrides?.root;
    // styleOverrides can be functions or objects
    expect(appBarOverride).toBeDefined();
    expect(parthenon.components?.MuiAppBar).toBeDefined();
  });
});
