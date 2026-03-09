import type { CanyoningData } from '@/types/journals';

function hasGaugeName(value: string | null | undefined): value is string {
  return value != null && value !== '';
}

export function buildCanyonFlags(canyoningData?: CanyoningData): string[] {
  return [
    canyoningData?.is_vertical ? 'Vertical' : null,
    canyoningData?.is_night_canyon ? 'Night Canyon' : null,
    canyoningData?.is_white_water ? 'White Water' : null,
  ].filter((flag): flag is string => flag !== null);
}

export function getWaterGaugeLabel(
  canyoningData?: Pick<CanyoningData, 'water_guage_name' | 'water_guage_level'>
): string | null {
  const waterGaugeName = canyoningData?.water_guage_name;
  const waterGaugeLevel = canyoningData?.water_guage_level;

  if (!hasGaugeName(waterGaugeName) && waterGaugeLevel == null) {
    return null;
  }

  return `${hasGaugeName(waterGaugeName) ? waterGaugeName : 'Gauge'}${
    waterGaugeLevel != null ? ` (${waterGaugeLevel})` : ''
  }`;
}
