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
  /**
   * The ISO 3166-1 alpha-2 country filled in for imported addresses that have
   * none, or `null` if the user has not chosen one.
   */
  default_country?: string | null;
}

/**
 * A partial settings update: an omitted field is left as it is, and
 * `default_country: null` clears the country. The timezone cannot be cleared.
 */
export interface UserSettingsPatch {
  timezone?: string;
  default_country?: string | null;
}

export interface UserSettingsResource {
  id: string;
  type: 'user_settings';
  attributes: UserSettingsAttributes;
}

export interface UserSettingsResponse {
  data: UserSettingsResource;
}
