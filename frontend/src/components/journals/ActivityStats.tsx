import {
  Activity,
  Clock,
  Flame,
  Heart,
  Mountain,
  Ruler,
  Cloud,
  Compass,
} from 'lucide-react';
import type {
  AbseilingData,
  CanyoningData,
  ClimbingData,
  CrossCountrySkiingData,
  FitnessData,
  BushwalkingData,
  JoggingData,
  KayakingData,
  OutdoorActivityData,
} from '@/types/journals';
import type { Route } from '@/types/routes';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';

interface ActivityStatsProps {
  readonly data?: FitnessData;
  readonly outdoorData?: OutdoorActivityData;
  readonly joggingData?: JoggingData;
  readonly bushwalkingData?: BushwalkingData;
  readonly abseilingData?: AbseilingData;
  readonly canyoningData?: CanyoningData;
  readonly climbingData?: ClimbingData;
  readonly kayakingData?: KayakingData;
  readonly crossCountrySkiingData?: CrossCountrySkiingData;
  readonly routeDisplay?: Route;
  readonly className?: string;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(2)} km`;
  }
  return `${meters} m`;
}

export function formatPace(
  durationSecs: number,
  distanceMeters: number
): string {
  if (distanceMeters === 0) return '-';
  const km = distanceMeters / 1000;
  const secsPerKm = durationSecs / km;
  const m = Math.floor(secsPerKm / 60);
  const s = Math.floor(secsPerKm % 60);
  return `${m}:${s.toString().padStart(2, '0')} /km`;
}

/**
 * Format an already-computed seconds-per-km pace value into "mm:ss /km".
 * Use this instead of formatPace() when the pace is already known.
 */
export function formatSecondsPerKm(secsPerKm: number): string {
  const m = Math.floor(secsPerKm / 60);
  const s = Math.floor(secsPerKm % 60);
  return `${m}:${s.toString().padStart(2, '0')} /km`;
}

interface StatItemProps {
  readonly icon: React.ReactNode;
  readonly label: string;
  readonly value: React.ReactNode;
  readonly testId?: string;
}

function StatItem({ icon, label, value, testId }: StatItemProps) {
  return (
    <div className='flex items-center gap-3'>
      <div className='bg-primary/10 text-primary rounded-full p-2'>{icon}</div>
      <div>
        <p className='text-muted-foreground text-xs font-medium'>{label}</p>
        <p className='text-sm font-semibold' data-testid={testId}>
          {value}
        </p>
      </div>
    </div>
  );
}

interface StatsSectionProps {
  readonly title: string;
  readonly description: string;
  readonly items: readonly React.ReactNode[];
  readonly testId: string;
}

interface StatConfig {
  readonly key: string;
  readonly icon: React.ReactNode;
  readonly label: string;
  readonly value: React.ReactNode;
  readonly testId: string;
}

function StatsSection({
  title,
  description,
  items,
  testId,
}: StatsSectionProps) {
  return (
    <section className='space-y-3' data-testid={testId}>
      <div className='space-y-1'>
        <h3 className='text-sm font-semibold'>{title}</h3>
        <p className='text-muted-foreground text-xs'>{description}</p>
      </div>
      <div className='grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3'>
        {items}
      </div>
    </section>
  );
}

function isPositiveNumber(value: number | null | undefined): value is number {
  return value != null && value > 0;
}

function isNonEmptyString(value: string | null | undefined): value is string {
  return value != null && value !== '';
}

function createStatItem({ key, icon, label, value, testId }: StatConfig) {
  return (
    <StatItem
      key={key}
      icon={icon}
      label={label}
      value={value}
      testId={testId}
    />
  );
}

function compactStatItems(
  items: Array<React.ReactNode | null>
): React.ReactNode[] {
  return items.filter((item): item is React.ReactNode => item !== null);
}

function buildCanyonFlags(canyoningData?: CanyoningData): string[] {
  return [
    canyoningData?.is_vertical ? 'Vertical' : null,
    canyoningData?.is_night_canyon ? 'Night Canyon' : null,
    canyoningData?.is_white_water ? 'White Water' : null,
  ].filter((flag): flag is string => flag !== null);
}

function getWaterGaugeLabel(
  waterGaugeName: string | null | undefined,
  waterGaugeLevel: number | null | undefined
): string | null {
  if (!isNonEmptyString(waterGaugeName) && waterGaugeLevel == null) {
    return null;
  }

  return `${waterGaugeName ?? 'Gauge'}${
    waterGaugeLevel != null ? ` (${waterGaugeLevel})` : ''
  }`;
}

function buildPerformanceItems({
  distance,
  duration,
  elevationGain,
  averageHeartRate,
  calories,
  joggingPace,
}: {
  readonly distance: number | null | undefined;
  readonly duration: number | null | undefined;
  readonly elevationGain: number | null | undefined;
  readonly averageHeartRate: number | null | undefined;
  readonly calories: number | null | undefined;
  readonly joggingPace: number | null | undefined;
}): React.ReactNode[] {
  const calculatedPace =
    isPositiveNumber(distance) &&
    isPositiveNumber(duration) &&
    !isPositiveNumber(joggingPace)
      ? formatPace(duration, distance)
      : null;

  return compactStatItems([
    isPositiveNumber(distance)
      ? createStatItem({
          key: 'distance',
          icon: <Ruler className='h-4 w-4' />,
          label: 'Distance',
          value: formatDistance(distance),
          testId: 'stat-distance',
        })
      : null,
    isPositiveNumber(duration)
      ? createStatItem({
          key: 'duration',
          icon: <Clock className='h-4 w-4' />,
          label: 'Duration',
          value: formatDuration(duration),
          testId: 'stat-duration',
        })
      : null,
    isPositiveNumber(joggingPace)
      ? createStatItem({
          key: 'pace-jogging',
          icon: <Activity className='h-4 w-4' />,
          label: 'Pace',
          value: formatSecondsPerKm(joggingPace),
          testId: 'stat-pace-jogging',
        })
      : null,
    calculatedPace
      ? createStatItem({
          key: 'pace',
          icon: <Activity className='h-4 w-4' />,
          label: 'Pace',
          value: calculatedPace,
          testId: 'stat-pace',
        })
      : null,
    isPositiveNumber(elevationGain)
      ? createStatItem({
          key: 'elevation',
          icon: <Mountain className='h-4 w-4' />,
          label: 'Elevation Gain',
          value: `${elevationGain} m`,
          testId: 'stat-elevation',
        })
      : null,
    isPositiveNumber(averageHeartRate)
      ? createStatItem({
          key: 'hr',
          icon: <Heart className='h-4 w-4' />,
          label: 'Avg HR',
          value: `${averageHeartRate} bpm`,
          testId: 'stat-hr',
        })
      : null,
    isPositiveNumber(calories)
      ? createStatItem({
          key: 'calories',
          icon: <Flame className='h-4 w-4' />,
          label: 'Calories',
          value: `${calories} kcal`,
          testId: 'stat-calories',
        })
      : null,
  ]);
}

function buildContextItems({
  routeDisplay,
  weatherConditions,
  trackGrading,
  waterGaugeName,
  waterGaugeLevel,
  waterType,
  snowConditions,
}: {
  readonly routeDisplay?: Route;
  readonly weatherConditions: string | null | undefined;
  readonly trackGrading: string | null | undefined;
  readonly waterGaugeName: string | null | undefined;
  readonly waterGaugeLevel: number | null | undefined;
  readonly waterType: string | null | undefined;
  readonly snowConditions: string | null | undefined;
}): React.ReactNode[] {
  const waterGaugeLabel = getWaterGaugeLabel(waterGaugeName, waterGaugeLevel);

  return compactStatItems([
    routeDisplay
      ? createStatItem({
          key: 'route',
          icon: <Mountain className='h-4 w-4' />,
          label: 'Route',
          value: routeDisplay.name,
          testId: 'stat-route',
        })
      : null,
    isNonEmptyString(weatherConditions)
      ? createStatItem({
          key: 'weather',
          icon: <Cloud className='h-4 w-4' />,
          label: 'Weather',
          value: weatherConditions,
          testId: 'stat-weather',
        })
      : null,
    isNonEmptyString(trackGrading)
      ? createStatItem({
          key: 'grading',
          icon: <Compass className='h-4 w-4' />,
          label: 'Track Grade',
          value: trackGrading,
          testId: 'stat-grading',
        })
      : null,
    waterGaugeLabel
      ? createStatItem({
          key: 'water-gauge',
          icon: <Cloud className='h-4 w-4' />,
          label: 'Water Gauge',
          value: waterGaugeLabel,
          testId: 'stat-water-gauge',
        })
      : null,
    isNonEmptyString(waterType)
      ? createStatItem({
          key: 'water-type',
          icon: <Cloud className='h-4 w-4' />,
          label: 'Water Type',
          value: waterType,
          testId: 'stat-water-type',
        })
      : null,
    isNonEmptyString(snowConditions)
      ? createStatItem({
          key: 'snow-conditions',
          icon: <Cloud className='h-4 w-4' />,
          label: 'Snow Conditions',
          value: snowConditions,
          testId: 'stat-snow-conditions',
        })
      : null,
  ]);
}

function buildTechnicalItems({
  numberOfAbseils,
  totalLength,
  frenchGrade,
  canyonFlags,
  climbingType,
  climbingGrade,
  climbingLength,
}: {
  readonly numberOfAbseils: number | null | undefined;
  readonly totalLength: number | null | undefined;
  readonly frenchGrade: string | null | undefined;
  readonly canyonFlags: string[];
  readonly climbingType: string | null | undefined;
  readonly climbingGrade: number | null | undefined;
  readonly climbingLength: number | null | undefined;
}): React.ReactNode[] {
  return compactStatItems([
    isPositiveNumber(numberOfAbseils)
      ? createStatItem({
          key: 'abseils',
          icon: <Activity className='h-4 w-4' />,
          label: 'Abseils',
          value: numberOfAbseils,
          testId: 'stat-abseils',
        })
      : null,
    isPositiveNumber(totalLength)
      ? createStatItem({
          key: 'total-length',
          icon: <Ruler className='h-4 w-4' />,
          label: 'Total Length',
          value: `${totalLength} m`,
          testId: 'stat-total-length',
        })
      : null,
    isNonEmptyString(frenchGrade)
      ? createStatItem({
          key: 'french-grade',
          icon: <Compass className='h-4 w-4' />,
          label: 'French Grade',
          value: frenchGrade,
          testId: 'stat-french-grade',
        })
      : null,
    canyonFlags.length > 0
      ? createStatItem({
          key: 'canyon-flags',
          icon: <Mountain className='h-4 w-4' />,
          label: 'Canyon Flags',
          value: canyonFlags.join(', '),
          testId: 'stat-canyon-flags',
        })
      : null,
    isNonEmptyString(climbingType)
      ? createStatItem({
          key: 'climbing-type',
          icon: <Activity className='h-4 w-4' />,
          label: 'Climbing Type',
          value: climbingType,
          testId: 'stat-climbing-type',
        })
      : null,
    isPositiveNumber(climbingGrade)
      ? createStatItem({
          key: 'climbing-grade',
          icon: <Compass className='h-4 w-4' />,
          label: 'Climbing Grade',
          value: climbingGrade,
          testId: 'stat-climbing-grade',
        })
      : null,
    isPositiveNumber(climbingLength)
      ? createStatItem({
          key: 'climbing-length',
          icon: <Ruler className='h-4 w-4' />,
          label: 'Climbing Length',
          value: `${climbingLength} m`,
          testId: 'stat-climbing-length',
        })
      : null,
  ]);
}

export function ActivityStats({
  data,
  outdoorData,
  joggingData,
  bushwalkingData,
  abseilingData,
  canyoningData,
  climbingData,
  kayakingData,
  crossCountrySkiingData,
  routeDisplay,
  className,
}: ActivityStatsProps) {
  const fitness = data ?? {};
  const distance = fitness.distance;
  const duration = fitness.duration;
  const elevationGain = fitness.elevation_gain;
  const averageHeartRate = fitness.heart_rate_avg;
  const calories = fitness.calories;
  const weatherConditions = outdoorData?.weather_conditions;
  const trackGrading = bushwalkingData?.track_grading;
  const numberOfAbseils = abseilingData?.number_of_abseils;
  const totalLength = abseilingData?.total_length;
  const frenchGrade = canyoningData?.french_grade;
  const waterGaugeName = canyoningData?.water_guage_name;
  const waterGaugeLevel = canyoningData?.water_guage_level;
  const climbingType = climbingData?.climbing_type;
  const climbingGrade = climbingData?.grade;
  const climbingLength = climbingData?.length;
  const waterType = kayakingData?.water_type;
  const snowConditions = crossCountrySkiingData?.snow_conditions;
  const joggingPace = joggingData?.pace;
  const canyonFlags = buildCanyonFlags(canyoningData);
  const performanceItems = buildPerformanceItems({
    distance,
    duration,
    elevationGain,
    averageHeartRate,
    calories,
    joggingPace,
  });
  const contextItems = buildContextItems({
    routeDisplay,
    weatherConditions,
    trackGrading,
    waterGaugeName,
    waterGaugeLevel,
    waterType,
    snowConditions,
  });
  const technicalItems = buildTechnicalItems({
    numberOfAbseils,
    totalLength,
    frenchGrade,
    canyonFlags,
    climbingType,
    climbingGrade,
    climbingLength,
  });

  const sections = [
    {
      key: 'performance',
      title: 'Performance',
      description: 'Distance, duration, pace, and effort metrics.',
      items: performanceItems,
    },
    {
      key: 'context',
      title: 'Route & Conditions',
      description: 'Route context, terrain, and current conditions.',
      items: contextItems,
    },
    {
      key: 'technical',
      title: 'Technical Details',
      description: 'Activity-specific grades, lengths, and specialist details.',
      items: technicalItems,
    },
  ].filter(section => section.items.length > 0);

  if (sections.length === 0) {
    return null; // Don't render empty card
  }

  return (
    <Card className={className} data-testid='activity-stats-grid'>
      <CardHeader className='pb-4'>
        <CardTitle className='text-base'>Activity highlights</CardTitle>
        <CardDescription>
          Performance, route context, and technical details for this activity.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        {sections.map((section, index) => (
          <div key={section.key} className='space-y-4'>
            <StatsSection
              title={section.title}
              description={section.description}
              items={section.items}
              testId={`activity-stats-section-${section.key}`}
            />
            {index < sections.length - 1 && <Separator />}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
