'use client';

import * as React from 'react';
import { RouteSelector } from '@/components/routes/RouteSelector';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card';
import { Providers } from '@/lib/providers';

export default function RouteSelectorSandbox() {
  const [selectedRouteId, setSelectedRouteId] = React.useState<string | null>(
    null
  );

  return (
    <Providers>
      <div className='bg-background flex min-h-screen flex-col items-center justify-center p-8'>
        <Card className='w-[400px]'>
          <CardHeader>
            <CardTitle>Route Selector Sandbox</CardTitle>
            <CardDescription>
              Test environment for the RouteSelector component.
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-4'>
            <div className='space-y-2'>
              <label htmlFor='route-selector' className='text-sm font-medium'>
                Select Route
              </label>
              <RouteSelector
                id='route-selector'
                value={selectedRouteId}
                onChange={setSelectedRouteId}
              />
            </div>

            <div className='border-t pt-4'>
              <h3 className='mb-2 text-sm font-medium'>State:</h3>
              <pre
                data-testid='selected-value'
                className='bg-muted rounded p-2 text-xs'
              >
                {JSON.stringify({ selectedRouteId }, null, 2)}
              </pre>
            </div>

            <div className='border-border space-y-2 border-t pt-4'>
              <h3 className='text-sm font-medium'>Additional Controls</h3>
              <button
                data-testid='clear-btn'
                onClick={() => setSelectedRouteId(null)}
                className='text-primary text-xs underline'
              >
                Clear Selection
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </Providers>
  );
}
