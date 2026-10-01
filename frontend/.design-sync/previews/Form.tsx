import * as React from 'react';
import { useForm } from 'react-hook-form';
import {
  Button,
  Checkbox,
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from 'lifecontour-frontend';

type EntryValues = {
  title: string;
  entryType: string;
  notes: string;
  linkContacts: boolean;
};

export function NewEntry() {
  const form = useForm<EntryValues>({
    defaultValues: {
      title: 'Coffee with Priya',
      entryType: 'event',
      notes: 'Caught up at Seven Seeds. She has just moved to Brunswick.',
      linkContacts: true,
    },
  });

  return (
    <Form {...form}>
      <form className='flex max-w-sm flex-col gap-4'>
        <FormField
          control={form.control}
          name='title'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Title</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormDescription>
                Shown in the journal list and the exported logbook.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='entryType'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Entry type</FormLabel>
              <Select value={field.value} onValueChange={field.onChange}>
                <FormControl>
                  <SelectTrigger className='w-full'>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value='note'>Note</SelectItem>
                  <SelectItem value='event'>Event</SelectItem>
                  <SelectItem value='mood'>Mood rating</SelectItem>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='notes'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Notes</FormLabel>
              <FormControl>
                <Textarea rows={3} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button type='submit'>Save entry</Button>
      </form>
    </Form>
  );
}

export function WithErrors() {
  const form = useForm<EntryValues>({
    defaultValues: {
      title: '',
      entryType: 'event',
      notes: 'Coffee',
      linkContacts: false,
    },
  });

  React.useEffect(() => {
    form.setError('title', {
      type: 'required',
      message: 'A title is required.',
    });
    form.setError('notes', {
      type: 'minLength',
      message: 'Notes must be at least 20 characters.',
    });
  }, [form]);

  return (
    <Form {...form}>
      <form className='flex max-w-sm flex-col gap-4'>
        <FormField
          control={form.control}
          name='title'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Title</FormLabel>
              <FormControl>
                <Input placeholder='Morning run' {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='notes'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Notes</FormLabel>
              <FormControl>
                <Textarea rows={3} {...field} />
              </FormControl>
              <FormDescription>
                Give yourself enough context to remember the day.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button type='submit'>Save entry</Button>
      </form>
    </Form>
  );
}

export function CheckboxField() {
  const form = useForm<EntryValues>({
    defaultValues: {
      title: 'Morning run',
      entryType: 'note',
      notes: '',
      linkContacts: true,
    },
  });

  return (
    <Form {...form}>
      <form className='flex max-w-sm flex-col gap-4'>
        <FormField
          control={form.control}
          name='linkContacts'
          render={({ field }) => (
            <FormItem className='flex items-start gap-2'>
              <FormControl>
                <Checkbox
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  className='mt-1'
                />
              </FormControl>
              <div className='flex flex-col gap-2'>
                <FormLabel>Link mentioned contacts</FormLabel>
                <FormDescription>
                  People named in the entry are matched to your contacts on
                  save.
                </FormDescription>
              </div>
            </FormItem>
          )}
        />
        <Button type='submit' variant='outline'>
          Save preferences
        </Button>
      </form>
    </Form>
  );
}
