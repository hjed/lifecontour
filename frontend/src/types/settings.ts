/**
 * User settings types matching backend API schemas (JSON:API).
 */

export interface UserSettingsAttributes {
  timezone: string;
}

export interface UserSettingsResource {
  id: string;
  type: 'user_settings';
  attributes: UserSettingsAttributes;
}

export interface UserSettingsResponse {
  data: UserSettingsResource;
}
