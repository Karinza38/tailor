"""Data model for the tailor app.

Implements a model to contain the data values as a backend for the
table view used in the app. This class provides an API specific to Tailor.
"""

import pathlib
import re

import asteval
import numpy as np
import pandas as pd

from tailor.cst_names import get_variable_names, rename_variables
from tailor.csv_format_dialog import FormatParameters


class DataModel:
    """Data model for the tailor app.

    Implements a model to contain the data values as a backend for the
    table view used in the app. This class provides an API specific to Tailor.
    """

    _data: pd.DataFrame
    _new_col_num: int = 0
    # column labels -> names
    _col_names: dict[str, str]
    _calculated_column_expression: dict[str, str]
    _is_calculated_column_valid: dict[str, bool]

    def __init__(self) -> None:
        self._data = pd.DataFrame()
        self._col_names = {}
        self._calculated_column_expression = {}
        self._is_calculated_column_valid = {}

    def num_rows(self):
        """Return the number of rows in the table."""
        return len(self._data)

    def num_columns(self):
        """Return the number of columns in the table."""
        return len(self._data.columns)

    def get_value(self, row: int, column: int):
        """Get value at row, column in table

        Args:
            row (int): row number
            column (int): column number
        """
        return self._data.iat[row, column]

    def get_values(
        self, start_row: int, start_column: int, end_row: int, end_column: int
    ) -> np.ndarray:
        values = self._data.iloc[start_row : end_row + 1, start_column : end_column + 1]
        return values.to_numpy()

    def set_value(self, row: int, column: int, value: float):
        """Set value at row, column in table.

        Args:
            row (int): row number
            column (int): column number
            value (float): value to insert
        """
        self._data.iat[row, column] = value
        label = self.get_column_label(column)
        self.recalculate_columns_from(label)

    def set_values(
        self,
        start_row: int,
        start_column: int,
        end_row: int,
        end_column: int,
        value: float,
    ):
        """Set a block of table cells to some (single) value.

        The block of cells is specified using start and end indexes for rows and
        columns. Interpreted as a rectangular selection, the starting indexes
        specify the location of the topleft corner while the ending indexes
        specify the bottomright corner. All cells within this selection are set
        to the same specified value.

        Args:
            start_row (int): top left row number.
            start_column (int): top left column number.
            end_row (int): bottom right row number.
            end_column (int): bottom right column number.
            value (float): the value to set all cells to.
        """
        self._data.iloc[start_row : end_row + 1, start_column : end_column + 1] = value
        label = self.get_column_label(start_column)
        self.recalculate_columns_from(label)

    def set_values_from_array(
        self,
        start_row: int,
        start_column: int,
        values: np.ndarray,
    ):
        """Set a block of table cells to values from an array.

        The block of cells is specified using only start indexes for rows and
        columns. The width and height of the block are determined by the size of
        the array. All cells within this block are set to the values contained
        within the array. The end result is pasting the array directly into the
        table.

        Args:
            start_row (int): top left row number.
            start_column (int): top left column number.
            values (np.ndarray): the values to insert into the cells.
        """
        height, width = values.shape
        self._data.iloc[
            start_row : start_row + height, start_column : start_column + width
        ] = values
        label = self.get_column_label(start_column)
        self.recalculate_columns_from(label)

    def insert_rows(self, row: int, count: int):
        """Insert rows into the table.

        Insert `count` rows into the table at position `row`.

        Args:
            row (int): an integer row number to indicate the place of insertion.
            count (int): number of rows to insert
        """
        new_data = pd.DataFrame.from_dict(
            {col: count * [np.nan] for col in self._data.columns}
        )
        self._data = pd.concat(
            [self._data.iloc[:row], new_data, self._data.iloc[row:]]
        ).reset_index(drop=True)
        self.recalculate_all_columns()

    def remove_rows(self, row: int, count: int):
        """Remove rows from the table.

        Removes a row at the specified row number.

        Args:
            row (int): the first row to remove.
            count (int): the number of rows to remove.
        """
        self._data = self._data.drop(index=range(row, row + count)).reset_index(
            drop=True
        )

    def insert_columns(self, column: int, count: int):
        """Insert columns into the table.

        Insert columns *before* the specified column number.

        Args:
            column (int): a column number to indicate the place of insertion.
            count (int): the number of columns to insert.

        Returns:
            A list of inserted column labels.
        """
        labels = [self._create_new_column_label() for _ in range(count)]
        for idx, label in zip(range(column, column + count), labels):
            self._data.insert(idx, label, np.nan)
            self._col_names[label] = label
        return labels

    def remove_columns(self, column: int, count: int):
        """Remove columns from the table.

        Removes a column at the specified column number.

        Args:
            column (int): a column number to indicate the place of removal.
            count (int): the number of columns to remove.
        """
        labels = self._data.columns[column : column + count]
        self._data.drop(columns=labels, inplace=True)
        for label in labels:
            if self.is_calculated_column(label):
                del self._calculated_column_expression[label]
            del self._col_names[label]

        # if there are columns left to the right of the removed column(s),
        # recalculate them
        if column < self.num_columns():
            new_label_at_idx = self.get_column_label(column)
            self.recalculate_columns_from(new_label_at_idx)

    def move_column(self, source: int, dest: int):
        """Move a column in the table.

        Moves a column from the source index to the dest index. Contrary to Qt
        conventions the dest index is the index in the final table, _after_ the
        move operation is completed. So, if you have the initial state:

            col0, col1, col2, col3

        and you want to end up with the final state:

            col1, col2, col0, col3

        you should call `move_column(0, 2)` to move col0 from index 0 to index
        2. By Qt conventions, you should call the Qt function with
        `moveColumn(0, 3)` because you want to place col0 _before_ col3. So pay
        attention to the correct arguments.

        Args:
            source (int): the original index of the column
            dest (int): the final index of the column
        """
        # reorder column labels
        cols = list(self._data.columns)
        cols.insert(dest, cols.pop(source))
        # reorder dataframe to conform to column labels
        self._data = self._data.reindex(columns=cols)
        label = self.get_column_label(min(source, dest))
        self.recalculate_columns_from(label)

    def is_empty(self):
        """Check whether all cells are empty."""
        # Rows or columns are dropped only if *all* values in that row or column
        # are NaN. Then, check if anything is left.
        return self._data.dropna(how="all").empty

    def insert_calculated_column(self, column: int) -> str:
        """Insert a calculated column.

        Insert a column *before* the specified column number. Returns True if
        the insertion was succesful.

        Args:
            column (int): an integer column number to indicate the place of
                insertion.

        Returns:
            str: the label of the inserted column.
        """
        (label,) = self.insert_columns(column, count=1)
        self._calculated_column_expression[label] = ""
        self._is_calculated_column_valid[label] = False
        return label

    def rename_column(self, label: str, name: str):
        """Rename a column.

        Args:
            label (str): the column label
            name (str): the new name for the column
        """
        new_name = self.normalize_column_name(name)
        self._col_names[label] = new_name
        return new_name

    def normalize_column_name(self, name):
        """Normalize column name.

        Change whitespace to underscores and add an underscore if the name
        starts with a number.

        Args:
            name (str): the name to normalize.

        Returns:
            str: the normalized name.
        """
        return re.sub(r"\W|^(?=\d)", "_", name)

    def get_column_expression(self, label: str):
        """Get column expression.

        Get the mathematical expression used to calculate values in the
        calculated column.

        Args:
            label (str): the column label.

        Returns:
            A string containing the mathematical expression or None.
        """
        expression = self._calculated_column_expression.get(label, None)

        if expression:
            try:
                var_names = get_variable_names(expression)
            except SyntaxError:
                return expression

            if (var_names - set(self._col_names.keys())) & set(
                self._col_names.values()
            ):
                # There seems to be a raw variable name (not label!) stored in
                # the expression. This can happen if you use a variable in your
                # expression which does not yet exist. When a column with that
                # name is created, the name (and not the label) is still stored
                # in the expression. Because the label is not stored, renaming
                # the column will not result in an updated expression. Try to
                # update the expression so that the name will be transformed
                # into a label. After that the column is locked in and can
                # safely be further renamed if necessary. False positives may
                # occur if columns are still named col1, col2, etc., but that is
                # ok.
                self.update_column_expression(label, expression)
            return rename_variables(expression, self._col_names)
        else:
            return None

    def update_column_expression(self, label: str, expression: str):
        """Update a calculated column with a new expression.

        Args:
            col_idx: an integer column number.
            expression: a string with a mathematical expression used to
                calculate the column values.
        """
        if self.is_calculated_column(label):
            # mapping: names -> labels, so must reverse _col_names mapping
            mapping = {v: k for k, v in self._col_names.items()}
            try:
                transformed = rename_variables(expression, mapping)
            except SyntaxError:
                transformed = expression
            self._calculated_column_expression[label] = transformed
            self.recalculate_columns_from(label)

    def recalculate_columns_from(self, label: str):
        """Recalculate all columns starting from the given column.

        When updating values or a column expression, you may want to also update
        all calculated columns to the right of the updated column. This method
        will evaluate all calculated columns starting from the specified label.

        Args:
            label (str): the column label to start from.
        """
        idx = self._data.columns.get_loc(label)
        for column in self._data.columns[idx:]:
            if self.is_calculated_column(column):
                self.recalculate_column(column)

    def recalculate_all_columns(self):
        """Recalculate all columns.

        If data is entered or changed, the calculated column values must be
        updated. This method will manually recalculate all column values, from left to right.
        """
        for column in self._data.columns:
            if self.is_calculated_column(column):
                self.recalculate_column(column)

    def recalculate_column(self, label: str) -> bool:
        """Recalculate column values.

        Calculate column values based on its expression. Each column can use
        values from columns to the left of itself. Those values can be accessed
        by using the column label (not the user-defined name!) as a variable in
        the expression.

        Args:
            label (str): the column label.

        Returns:
            True if the calculation was successful, False otherwise.
        """
        expression = self.get_column_expression(label)
        # set up interpreter
        objects = self._get_accessible_columns(label)
        aeval = asteval.Interpreter(usersyms=objects)
        try:
            # try to evaluate expression and cast output to a float (series)
            output = aeval(expression, show_errors=False, raise_errors=True)
            if isinstance(output, pd.Series) or isinstance(output, np.ndarray):
                output = output.astype("float64")
            else:
                output = float(output)
        except Exception as exc:
            # error in evaluation or output cannot be cast to a float (series)
            self._is_calculated_column_valid[label] = False
            return False
        else:
            # evaluation was successful
            self._data[label] = output
            self._is_calculated_column_valid[label] = True
            return True

    def _get_accessible_columns(self, label: str) -> dict[str, pd.Series]:
        """Get accessible column data for use in expressions.

        When calculating column values each column can access the values of the
        columns to its left by using the column name as a variable. This method
        returns the column data for the accessible columns. If the column data
        is not valid, the data is not returned and that will invalidate every
        calculated column using that column in an expression.

        Args:
            label (str): the label of the column that wants to access data.

        Returns:
            dict: a dictionary of column label, data value pairs.
        """
        # accessible columns to the left of current column
        idx = self._data.columns.get_loc(label)
        accessible_columns = self._data.columns[:idx]
        return {
            self.get_column_name(k): self._data[k]
            for k in accessible_columns
            if self.is_column_valid(k)
        }

    def get_column_label(self, column: int) -> str:
        """Get column label.

        Get column label at the given index.

        Args:
            column: an integer column number.

        Returns:
            The column label as a string.
        """
        return self._data.columns[column]

    def get_column_label_by_name(self, name: str) -> str:
        """Get column label by name.

        Get column label using the name of the column.

        Args:
            name: the name of the column.

        Returns:
            The column label as a string.
        """
        (label,) = [
            label for label, col_name in self._col_names.items() if col_name == name
        ]
        return label

    def get_column_labels(self) -> list[str]:
        """Get all column labels.

        Note: the column labels are guaranteed to be in the order they appear in
        the data.

        Returns:
            list[str]: a list of all column labels.
        """
        return list(self._data.columns)

    def get_column_name(self, label: str) -> str:
        """Get column name.

        Get column name at the given index.

        Args:
            label (str): the column label.

        Returns:
            The column name as a string.
        """
        return self._col_names[label]

    def get_column_names(self) -> list[str]:
        """Get all column names.

        Note: the column names are guaranteed to be in the order they appear in
        the data.

        Returns:
            list[str]: a list of all column names.
        """
        return [self.get_column_name(label) for label in self.get_column_labels()]

    def get_column(self, label: str):
        """Return column values.

        Args:
            label (str): the column label.

        Returns:
            An np.ndarray containing the column values.
        """
        return self._data[label].to_numpy()

    def is_calculated_column(self, label: str):
        """Check if column is calculated.

        Checks whether a column is calculated from a mathematical expression.

        Args:
            label (str): the column label.

        Returns:
            True if the column is calculated, False otherwise.
        """
        return label in self._calculated_column_expression

    def is_column_valid(self, label: str):
        """Check if a column has valid values.

        Checks whether the column contains the results of a valid calculation if
        it is a calculated column. When a calculation fails due to an invalid
        expression the values are invalid. If it is a regular data column, the
        values are always valid.

        Args:
            label (str): the column label.

        Returns:
            True if the column values are valid, False otherwise.
        """
        if not self.is_calculated_column(label):
            # values are not calculated, so are always valid
            return True
        else:
            return self._is_calculated_column_valid[label]

    def column_uses(self, label: str, labels: list[str]) -> bool:
        """Test whether column uses any of the listed columns.

        If the column `label` is a calculated column and uses any of the
        supplied `labels` in its expression, return True.

        Args:
            label (str): the column under test.
            labels (list[str]): the column labels to test.

        Returns:
            bool: True if any of the column labels are used.
        """
        if not self.is_calculated_column(label):
            return False
        expression = self._calculated_column_expression[label]
        try:
            variables = get_variable_names(expression)
        except SyntaxError:
            variables = set()
        if variables & set(labels):
            return True
        else:
            return False

    def _create_new_column_label(self):
        """Create a label for a new column.

        Creates column labels like col1, col2, etc.

        Returns:
            A string containing the new label.
        """
        self._new_col_num += 1
        return f"col{self._new_col_num}"

    def export_csv(self, filename: pathlib.Path) -> None:
        """Write all data to CSV file.

        Args:
            filename (pathlib.Path): the destination path.
        """
        self._data.to_csv(filename, index=False, header=self.get_column_names())

    def import_csv(
        self,
        filename: pathlib.Path | str,
        format: FormatParameters,
    ):
        """Read data from CSV file.

        Overwrites all existing data by importing a CSV file.

        Args:
            filename (pathlib.Path | str): a string containing the path to the CSV file
            format (FormatParameters): CSV format parameters
        """
        df = self.create_df_from_csv(filename, format)

        self._new_col_num = 0
        col_names = list(df.columns)
        col_labels = [self._create_new_column_label() for _ in range(len(df.columns))]

        self._data = df.rename(
            columns={name: label for name, label in zip(col_names, col_labels)}
        )
        self._col_names = {label: name for label, name in zip(col_labels, col_names)}
        self._calculated_column_expression = {}
        self._is_calculated_column_valid = {}

    def merge_csv(
        self,
        filename: pathlib.Path | str,
        format: FormatParameters,
    ):
        """Merge data from CSV file into existing data sheet.

        Overwrites all existing columns by importing a CSV file, but keeps other
        columns.

        Args:
            filename (pathlib.Path | str): a string containing the path to the CSV file
            format (FormatParameters): CSV format parameters
        """
        df = self.create_df_from_csv(filename, format)

        # prepare data for merge operation
        existing_col_names = self.get_column_names()
        for col_name in df.columns:
            # create labels for columns not yet in data
            if col_name not in existing_col_names:
                # insert column, does not really matter where
                (label,) = self.insert_columns(0, 1)
                self.rename_column(label, col_name)
            # if the column was previously calculated, remove expression
            label = self.get_column_label_by_name(col_name)
            if self.is_calculated_column(label):
                self._calculated_column_expression.pop(label)
                self._is_calculated_column_valid.pop(label)
        # rename columns to use labels instead of names
        import_data = df.rename(
            columns={name: label for label, name in self._col_names.items()}
        )

        # drop imported columns from existing data, ignore missing columns
        old_data = self._data.drop(import_data.columns, axis="columns", errors="ignore")
        # concatenate imported and old data
        new_data = pd.concat([import_data, old_data], axis="columns")
        # drop excess rows, if imported data is shorter than old data
        final_data = new_data.truncate(0, len(import_data) - 1)

        # save final data and recalculate values in calculated columns
        self._data = final_data
        self.recalculate_all_columns()

    def create_df_from_csv(
        self, path: pathlib.Path | str, format: FormatParameters
    ) -> pd.DataFrame:
        """Read CSV data into pandas DataFrame and normalize columns.

        Args:
            path (pathlib.path | str): path to the CSV file.
            format (FormatParameters): CSV format parameters.

        Returns:
            pd.DataFrame: the new data frame.
        """
        df = pd.read_csv(
            path,
            delimiter=format.delimiter,
            decimal=format.decimal,
            thousands=format.thousands,
            header=format.header,
            skiprows=format.skiprows,
        )
        # make sure column names are strings, even for numbered columns
        df.columns = df.columns.astype(str)
        # normalize column names to valid python variable names
        df.columns = df.columns.map(self.normalize_column_name)
        return df
