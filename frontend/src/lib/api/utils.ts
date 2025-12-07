/**
 * Shared API utilities for error handling and response processing.
 *
 * Provides consistent error handling across all API modules to eliminate
 * code duplication and ensure uniform error messages.
 */

import type { JsonApiErrorResponse } from '@/types/api';

/**
 * Extract error message from a JSON:API error response.
 *
 * Safely handles various response formats:
 * - Standard JSON:API errors with `errors[].detail`
 * - Non-JSON responses
 * - Malformed JSON responses
 *
 * @param response - The fetch Response object
 * @param defaultMessage - Fallback message if error extraction fails
 * @returns Error message string
 */
export async function extractErrorMessage(
  response: Response,
  defaultMessage: string
): Promise<string> {
  // Safely get content-type, handling cases where headers might not be defined
  const contentType = response.headers?.get('content-type');

  // Only try to parse JSON if content-type indicates JSON
  if (contentType && contentType.includes('application/json')) {
    try {
      const errorData: JsonApiErrorResponse = await response.json();

      // Validate JSON:API error structure
      if (
        Array.isArray(errorData.errors) &&
        errorData.errors.length > 0 &&
        typeof errorData.errors[0].detail === 'string'
      ) {
        return errorData.errors[0].detail;
      }

      // JSON parsed but doesn't match expected structure
      return `${defaultMessage} (Status: ${response.status})`;
    } catch {
      // JSON parsing failed - include status info for debugging
      return `${defaultMessage} (Status: ${response.status} ${response.statusText})`;
    }
  }

  // Non-JSON response - include status info
  return `${defaultMessage} (Status: ${response.status} ${response.statusText})`;
}

/**
 * Handle API response with typed error handling.
 *
 * Standard handler for API responses that:
 * - Returns parsed JSON for successful responses
 * - Throws Error with extracted message for failed responses
 *
 * @param response - The fetch Response object
 * @param defaultErrorMessage - Fallback error message
 * @returns Parsed JSON response data
 * @throws Error with extracted or default message
 */
export async function handleApiResponse<T>(
  response: Response,
  defaultErrorMessage: string = 'Request failed'
): Promise<T> {
  if (!response.ok) {
    const errorMessage = await extractErrorMessage(
      response,
      defaultErrorMessage
    );
    throw new Error(errorMessage);
  }
  return response.json();
}

/**
 * Handle API response for void/empty responses.
 *
 * For endpoints that don't return a body (e.g., DELETE).
 *
 * @param response - The fetch Response object
 * @param defaultErrorMessage - Fallback error message
 * @throws Error with extracted or default message
 */
export async function handleApiVoidResponse(
  response: Response,
  defaultErrorMessage: string = 'Request failed'
): Promise<void> {
  if (!response.ok) {
    const errorMessage = await extractErrorMessage(
      response,
      defaultErrorMessage
    );
    throw new Error(errorMessage);
  }
}
