/**
 * A jsdom test environment with the process timezone pinned.
 *
 * Some behaviour is only wrong in one direction from UTC — writing a date as
 * the UTC instant of local midnight, for instance, is indistinguishable from
 * writing UTC midnight unless the offset is non-zero and negative. Asserting
 * that in the ambient zone means the test proves something different on a
 * developer's machine than it does in CI, and nothing at all in UTC.
 *
 * Setting `process.env.TZ` from inside a test file does not work: jest gives
 * each file a *copy* of `process.env`, so the assignment never reaches the
 * setter Node watches to invalidate its timezone cache. A test environment,
 * however, is constructed in the worker process itself, before the sandbox
 * exists — so the assignment lands on the real `process.env` and takes effect.
 *
 * Workers are reused across files, so the ambient zone is restored on
 * teardown rather than left set for whatever runs next.
 *
 * Usage — a docblock at the top of the test file:
 *
 *     /**
 *      * (at)jest-environment <rootDir>/jest.timezone-environment.cjs
 *      * (at)jest-environment-options {"timezone": "America/New_York"}
 *      *\/
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const JSDOMEnvironment = require('jest-environment-jsdom').default;

/** Pinning to UTC is the useful default: it is the one zone CI may not be in. */
const DEFAULT_TIMEZONE = 'UTC';

class TimezoneEnvironment extends JSDOMEnvironment {
  constructor(config, context) {
    // Before `super`, so jsdom is built with the zone already in force.
    const ambient = process.env.TZ;
    process.env.TZ =
      config.projectConfig.testEnvironmentOptions.timezone ?? DEFAULT_TIMEZONE;
    super(config, context);
    this.ambientTimezone = ambient;
  }

  async teardown() {
    if (this.ambientTimezone === undefined) {
      delete process.env.TZ;
    } else {
      process.env.TZ = this.ambientTimezone;
    }
    await super.teardown();
  }
}

module.exports = TimezoneEnvironment;
