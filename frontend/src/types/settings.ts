/**
 * User settings types matching backend API schemas (JSON:API).
 */

export interface UserSettingsAttributes {
  /**
   * The timezone the user has configured, or `null` if they never have.
   *
   * `null` is not the same as `'UTC'`, and the backend deliberately keeps the
   * two apart: a caller that anchors day boundaries on this value falls back
   * to the browser's zone when it is absent, which is the right answer for a
   * user who has not told us where they are, and the wrong one for a user who
   * chose UTC on purpose.
   */
  timezone: string | null;
}

export interface UserSettingsResource {
  id: string;
  type: 'user_settings';
  attributes: UserSettingsAttributes;
}

export interface UserSettingsResponse {
  data: UserSettingsResource;
}
