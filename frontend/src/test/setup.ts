// Vitest global setup: adds the jest-dom matchers (toBeInTheDocument, etc.)
// and cleans the rendered DOM between tests so one test can't see another's.
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => cleanup());
