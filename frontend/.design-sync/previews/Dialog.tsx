import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Textarea,
} from 'personal-management-frontend';

export function EditEntry() {
  return (
    <Dialog open modal={false}>
      {/* The real Dialog autofocuses its first field, which leaves a selection
          highlight in a static screenshot. Suppressed for the preview only. */}
      <DialogContent
        className='sm:max-w-md'
        onOpenAutoFocus={e => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Edit journal entry</DialogTitle>
          <DialogDescription>
            Update the title and notes for this entry. Changes are saved to your
            history.
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4 py-2'>
          <div className='grid gap-2'>
            <Label htmlFor='entry-title'>Title</Label>
            <Input id='entry-title' defaultValue='Morning run' />
          </div>
          <div className='grid gap-2'>
            <Label htmlFor='entry-notes'>Notes</Label>
            <Textarea
              id='entry-notes'
              rows={3}
              defaultValue='8.2 km along the Yarra before work.'
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant='outline'>Cancel</Button>
          <Button>Save changes</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
