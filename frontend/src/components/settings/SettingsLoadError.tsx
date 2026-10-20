/** Shown by a settings card whose stored value could not be read. */
export function SettingsLoadError() {
  return (
    <p role='alert' className='text-destructive text-sm'>
      Could not load your settings. Reload the page to try again.
    </p>
  );
}
