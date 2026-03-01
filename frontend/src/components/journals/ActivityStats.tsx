import { Activity, Clock, Flame, Heart, Mountain, Ruler } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { FitnessData } from '@/types/journals';

interface ActivityStatsProps {
  readonly data: FitnessData;
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

export function ActivityStats({ data, className }: ActivityStatsProps) {
  const hasDistance = data.distance != null && data.distance > 0;
  const hasDuration = data.duration != null && data.duration > 0;
  const showPace = hasDistance && hasDuration;
  const hasElevation = data.elevation_gain != null && data.elevation_gain > 0;
  const hasHr = data.heart_rate_avg != null && data.heart_rate_avg > 0;
  const hasCalories = data.calories != null && data.calories > 0;

  if (!hasDistance && !hasDuration && !hasElevation && !hasHr && !hasCalories) {
    return null; // Don't render empty card
  }

  return (
    <Card className={cn('p-4', className)} data-testid='activity-stats-grid'>
      <div className='grid grid-cols-2 gap-4 md:grid-cols-3'>
        {hasDistance && (
          <StatItem
            icon={<Ruler className='h-4 w-4' />}
            label='Distance'
            value={formatDistance(data.distance!)}
            testId='stat-distance'
          />
        )}

        {hasDuration && (
          <StatItem
            icon={<Clock className='h-4 w-4' />}
            label='Duration'
            value={formatDuration(data.duration!)}
            testId='stat-duration'
          />
        )}

        {showPace && (
          <StatItem
            icon={<Activity className='h-4 w-4' />}
            label='Pace'
            value={formatPace(data.duration!, data.distance!)}
            testId='stat-pace'
          />
        )}

        {hasElevation && (
          <StatItem
            icon={<Mountain className='h-4 w-4' />}
            label='Elevation Gain'
            value={`${data.elevation_gain} m`}
            testId='stat-elevation'
          />
        )}

        {hasHr && (
          <StatItem
            icon={<Heart className='h-4 w-4' />}
            label='Avg HR'
            value={`${data.heart_rate_avg} bpm`}
            testId='stat-hr'
          />
        )}

        {hasCalories && (
          <StatItem
            icon={<Flame className='h-4 w-4' />}
            label='Calories'
            value={`${data.calories} kcal`}
            testId='stat-calories'
          />
        )}
      </div>
    </Card>
  );
}
