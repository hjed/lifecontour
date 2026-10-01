/**
 * Tests for Table components.
 *
 * Ensures accessibility compliance and proper semantic structure
 * following SonarQube quality standards.
 */

import { render, screen } from '@testing-library/react';
import {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableRowHeader,
  TableCaption,
} from '@/components/ui/table';

describe('Table Components', () => {
  it('should render a complete accessible table structure', () => {
    render(
      <Table>
        <TableCaption>Test table caption</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableRowHeader>John Doe</TableRowHeader>
            <TableCell>john@example.com</TableCell>
            <TableCell>Admin</TableCell>
          </TableRow>
          <TableRow>
            <TableRowHeader>Jane Smith</TableRowHeader>
            <TableCell>jane@example.com</TableCell>
            <TableCell>User</TableCell>
          </TableRow>
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell>Total</TableCell>
            <TableCell>2 users</TableCell>
            <TableCell></TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    );

    // Check table structure
    const table = screen.getByRole('table');
    expect(table).toBeInTheDocument();
    expect(table).toHaveAttribute('data-slot', 'table');

    // Check caption
    expect(screen.getByText('Test table caption')).toBeInTheDocument();

    // Check column headers have proper scope
    const columnHeaders = screen.getAllByRole('columnheader');
    expect(columnHeaders).toHaveLength(3);
    columnHeaders.forEach(header => {
      expect(header).toHaveAttribute('scope', 'col');
    });

    // Check row headers have proper scope
    const rowHeaders = screen.getAllByRole('rowheader');
    expect(rowHeaders).toHaveLength(2);
    rowHeaders.forEach(header => {
      expect(header).toHaveAttribute('scope', 'row');
    });

    // Check content
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
    expect(screen.getByText('Total')).toBeInTheDocument();
  });

  it('should apply custom className to table components', () => {
    render(
      <Table className='custom-table'>
        <TableHeader className='custom-header'>
          <TableRow className='custom-row'>
            <TableHead className='custom-head'>Header</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody className='custom-body'>
          <TableRow>
            <TableCell className='custom-cell'>Cell</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );

    const table = screen.getByRole('table');
    expect(table).toHaveClass('custom-table');

    const header = screen.getByRole('columnheader');
    expect(header).toHaveClass('custom-head');

    const cell = screen.getByRole('cell');
    expect(cell).toHaveClass('custom-cell');
  });

  it('should support table without caption', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Column 1</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>Data 1</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );

    const table = screen.getByRole('table');
    expect(table).toBeInTheDocument();
    expect(screen.getByText('Column 1')).toBeInTheDocument();
    expect(screen.getByText('Data 1')).toBeInTheDocument();
  });

  it('should support table with only regular cells (no row headers)', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>ID</TableHead>
            <TableHead>Value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>1</TableCell>
            <TableCell>First</TableCell>
          </TableRow>
          <TableRow>
            <TableCell>2</TableCell>
            <TableCell>Second</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );

    const table = screen.getByRole('table');
    expect(table).toBeInTheDocument();

    // Should have column headers
    const columnHeaders = screen.getAllByRole('columnheader');
    expect(columnHeaders).toHaveLength(2);

    // Should have regular cells
    const cells = screen.getAllByRole('cell');
    expect(cells).toHaveLength(4);

    // Should not have row headers
    const rowHeaders = screen.queryAllByRole('rowheader');
    expect(rowHeaders).toHaveLength(0);
  });

  it('should have proper accessibility attributes', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableRowHeader>Test User</TableRowHeader>
          </TableRow>
        </TableBody>
      </Table>
    );

    const table = screen.getByRole('table');
    expect(table).toHaveAttribute('role', 'table');

    const columnHeader = screen.getByRole('columnheader');
    expect(columnHeader).toHaveAttribute('scope', 'col');
    expect(columnHeader).toHaveAttribute('data-slot', 'table-head');

    const rowHeader = screen.getByRole('rowheader');
    expect(rowHeader).toHaveAttribute('scope', 'row');
    expect(rowHeader).toHaveAttribute('data-slot', 'table-row-header');
  });

  it('aligns row headers with the column headers above them', () => {
    // A <th> centres its text by default, so without an explicit alignment
    // a row header sits indented under its left-aligned column header.
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableRowHeader>Test User</TableRowHeader>
          </TableRow>
        </TableBody>
      </Table>
    );

    expect(screen.getByRole('columnheader')).toHaveClass('text-left');
    expect(screen.getByRole('rowheader')).toHaveClass('text-left');
  });
});
