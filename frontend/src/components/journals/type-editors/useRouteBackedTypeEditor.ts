import { useMemo } from 'react';
import { useRoute } from '@/lib/api/routes';
import { useTypeEditorState } from './useTypeEditorState';

interface RouteBackedTypeData {
  readonly route_id?: string | null;
}

interface UseRouteBackedTypeEditorOptions<T extends RouteBackedTypeData> {
  readonly data?: T;
  readonly defaultData: T;
  readonly onSave?: (data: T) => Promise<void>;
  readonly createMode?: boolean;
  readonly onChange?: (data: T) => void;
}

export function useRouteBackedTypeEditor<T extends RouteBackedTypeData>({
  data,
  defaultData,
  onSave,
  createMode = false,
  onChange,
}: UseRouteBackedTypeEditorOptions<T>) {
  const initialData = useMemo(() => data ?? defaultData, [data, defaultData]);
  const { data: routeData } = useRoute(initialData.route_id ?? '');
  const routeName = routeData?.data?.attributes?.name;

  return {
    initialData,
    routeName,
    ...useTypeEditorState({
      initialData,
      onSave,
      createMode,
      onChange,
    }),
  };
}
