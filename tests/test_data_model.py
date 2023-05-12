import numpy as np
import pandas as pd
import pytest
from PySide6 import QtCore
from pytest_mock import MockerFixture

from tailor.data_model import DataModel
from tailor.qdata_model import QDataModel


@pytest.fixture()
def model():
    yield DataModel()


@pytest.fixture()
def qmodel():
    yield QDataModel()


@pytest.fixture()
def bare_bones_data(qmodel: QDataModel):
    """Create a bare bones data model.

    This is an instance of QDataModel with a very basic data structure (five
    rows, two columns) and an updated column number variable, but nothing else.
    You can use this to test basic data manipulation required by Qt for
    subclasses of QAbstractDataModel.

    This fixture depends on certain implementation details.
    """
    qmodel._data = pd.DataFrame.from_dict(
        {
            "col0": [1.0, 2.0, 3.0, 4.0, 5.0],
            "col1": [6.0, 7.0, 8.0, 9.0, 10.0],
            "col2": [11.0, 12.0, 13.0, 14.0, 15.0],
        }
    )
    qmodel._new_col_num += 3
    yield qmodel


class TestImplementationDetails:
    def test_instance(self):
        assert issubclass(QDataModel, DataModel)

    def test_model_attributes(self, model: QDataModel):
        assert type(model._data) == pd.DataFrame
        assert model._new_col_num == 0

    def test_new_column_label(self, model: QDataModel):
        labels = [model._create_new_column_label() for _ in range(3)]
        assert labels == ["col1", "col2", "col3"]
        assert model._new_col_num == 3


class TestQtRequired:
    def test_rowCount(self, mocker: MockerFixture, qmodel: QDataModel):
        num_rows = mocker.patch.object(qmodel, "num_rows")
        assert qmodel.rowCount() == num_rows.return_value

    def test_rowCount_valid_parent(self, mocker: MockerFixture, qmodel: QDataModel):
        """Valid parent has no children in a table."""
        mocker.patch.object(qmodel, "num_rows")
        index = qmodel.createIndex(0, 0)
        assert qmodel.rowCount(index) == 0

    def test_columnCount(self, mocker: MockerFixture, qmodel: QDataModel):
        num_columns = mocker.patch.object(qmodel, "num_columns")
        assert qmodel.columnCount() == num_columns.return_value

    def test_columnCount_valid_parent(self, mocker: MockerFixture, qmodel: QDataModel):
        """Valid parent has no children in a table."""
        mocker.patch.object(qmodel, "num_columns")
        index = qmodel.createIndex(0, 0)
        assert qmodel.columnCount(index) == 0

    @pytest.mark.parametrize(
        "row, column, value, role",
        [
            (0, 0, 0.0, None),
            (2, 1, 4.2, QtCore.Qt.DisplayRole),
            (1, 7, 3.7, QtCore.Qt.EditRole),
        ],
    )
    def test_data_returns_data(
        self, mocker: MockerFixture, qmodel: QDataModel, row, column, value, role
    ):
        index = qmodel.createIndex(row, column)
        get_value = mocker.patch.object(qmodel, "get_value")
        get_value.return_value = value

        if not role:
            actual = qmodel.data(index)
        else:
            actual = qmodel.data(index, role)

        assert actual == f"{value:.10g}"

    def test_data_returns_None_for_invalid_role(self, qmodel: QDataModel):
        index = qmodel.createIndex(2, 1)
        value = qmodel.data(index, QtCore.Qt.DecorationRole)
        assert value is None

    def test_headerData(self, bare_bones_data: QDataModel):
        assert bare_bones_data.headerData(0, QtCore.Qt.Horizontal) == "col0"
        assert (
            bare_bones_data.headerData(1, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole)
            == "col1"
        )
        assert (
            bare_bones_data.headerData(
                0, QtCore.Qt.Horizontal, QtCore.Qt.DecorationRole
            )
            is None
        )
        assert bare_bones_data.headerData(3, QtCore.Qt.Vertical) == "4"

    def test_setData(self, bare_bones_data: QDataModel):
        # WIP: test that this method emits dataChanged
        index1 = bare_bones_data.createIndex(2, 1)
        index2 = bare_bones_data.createIndex(3, 0)

        retvalue1 = bare_bones_data.setData(index1, 1.7, QtCore.Qt.EditRole)
        retvalue2 = bare_bones_data.setData(index2, 4.2)
        retvalue3 = bare_bones_data.setData(index2, 5.0, QtCore.Qt.DecorationRole)

        assert retvalue1 == retvalue2 is True
        assert retvalue3 is False
        assert bare_bones_data._data.at[2, "col1"] == 1.7
        assert bare_bones_data._data.at[3, "col0"] == 4.2

    def test_flags(self, bare_bones_data: QDataModel):
        index = bare_bones_data.createIndex(2, 1)
        flags = bare_bones_data.flags(index)
        assert (
            flags
            == QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsSelectable
            | QtCore.Qt.ItemIsEditable
        )

    def test_insertRows(self, bare_bones_data: QDataModel):
        # WIP: test that begin/endInsertRows is called
        retvalue1 = bare_bones_data.insertRows(3, 4, parent=QtCore.QModelIndex())
        assert retvalue1 is True
        # check that all values are in inserted rows are NaN
        # use loc to check that the row labels are reindexed
        assert bool(bare_bones_data._data.loc[3:6].isna().all(axis=None)) is True
        assert list(bare_bones_data._data["col0"]) == pytest.approx(
            [
                1.0,
                2.0,
                3.0,
                np.nan,
                np.nan,
                np.nan,
                np.nan,
                4.0,
                5.0,
            ],
            nan_ok=True,
        )

    def test_insertRows_valid_parent(self, bare_bones_data: QDataModel):
        """You can't add rows inside cells."""
        assert (
            bare_bones_data.insertRows(0, 2, parent=bare_bones_data.createIndex(0, 0))
            is False
        )

    def test_removeRows(self, bare_bones_data: QDataModel):
        # WIP: test that begin/endRemoveRows is called
        retvalue = bare_bones_data.removeRows(1, 2)
        assert retvalue is True
        assert list(bare_bones_data._data["col0"]) == pytest.approx([1.0, 4.0, 5.0])
        assert list(bare_bones_data._data["col1"]) == pytest.approx([6.0, 9.0, 10.0])

    def test_removeRows_valid_parent(self, bare_bones_data: QDataModel):
        """You can't remove rows inside cells."""
        assert (
            bare_bones_data.removeRows(0, 2, parent=bare_bones_data.createIndex(0, 0))
            is False
        )

    def test_insertColumns(self, bare_bones_data: QDataModel):
        retvalue = bare_bones_data.insertColumns(1, 2)
        assert retvalue is True
        assert bare_bones_data._data.shape == (5, 5)
        assert list(bare_bones_data._data.iloc[0]) == pytest.approx(
            [1.0, np.nan, np.nan, 6.0, 11.0], nan_ok=True
        )

    def test_insertColumns_valid_parent(self, bare_bones_data: QDataModel):
        """You can't add columns inside cells."""
        assert (
            bare_bones_data.insertColumns(
                0, 2, parent=bare_bones_data.createIndex(0, 0)
            )
            is False
        )

    def test_removeColumns(self, bare_bones_data: QDataModel):
        retvalue = bare_bones_data.removeColumns(1, 2)
        assert retvalue is True
        assert bare_bones_data._data.shape == (5, 1)
        assert bare_bones_data._data.columns == ["col0"]

    def test_removeColumns_valid_parent(self, bare_bones_data: QDataModel):
        """You can't remove columns inside cells."""
        assert (
            bare_bones_data.removeColumns(
                0, 2, parent=bare_bones_data.createIndex(0, 0)
            )
            is False
        )


class TestDataModel:
    def test_num_rows_row_count(self, bare_bones_data: DataModel):
        assert bare_bones_data.num_rows() == 5

    def test_num_columns(self, bare_bones_data: DataModel):
        assert bare_bones_data.num_columns() == 3

    def test_data_returns_data(self, bare_bones_data: DataModel):
        assert bare_bones_data.get_value(2, 1) == 8.0
        assert bare_bones_data.get_value(3, 0) == 4.0
